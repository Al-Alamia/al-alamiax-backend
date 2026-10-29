from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction

from apps.notifications.services import notify
from apps.notifications.types import NotificationKinds

from .types import AMOUNT_METRICS, PlanKind, TierKind, TierVariant

MAX_TIERS_PER_VARIANT = 20
CENT = Decimal("0.01")


class PlanError(Exception):
    def __init__(self, code, message, errors=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors = errors or []


@dataclass
class EvalResult:
    amount: Decimal
    tier_index: "int | None"
    variant: str
    _tiers: list = field(default_factory=list, repr=False, compare=False)

    @property
    def tier(self):
        if self.tier_index is None or not self._tiers:
            return None
        return self._tiers[self.tier_index]


def _dec(raw):
    if isinstance(raw, bool) or raw is None:
        raise ValueError
    try:
        d = Decimal(str(raw).strip()) if not isinstance(raw, Decimal) else raw
    except InvalidOperation:
        raise ValueError
    if not d.is_finite():
        raise ValueError
    return d


def _get(t, name, alias):
    return t[name] if name in t else t.get(alias)


def _normalize(t):
    """Normalize a raw tier dict; raises ValueError on non-numeric input."""
    max_raw = _get(t, "max_value", "max")
    return {
        "variant": t.get("variant") or TierVariant.NORMAL,
        "min_value": _dec(_get(t, "min_value", "min")),
        "max_value": None if max_raw in (None, "") else _dec(max_raw),
        "kind": t.get("kind"),
        "value": _dec(t.get("value")),
    }


def validate_tiers(tiers, metric, threshold):
    errors = []
    normalized = []  # (original index, tier)
    for i, raw in enumerate(tiers):
        try:
            normalized.append((i, _normalize(raw)))
        except (ValueError, TypeError, AttributeError):
            errors.append({"index": i, "variant": str(raw.get("variant", "normal")) if isinstance(raw, dict) else "normal",
                           "message": "Tier values must be numeric."})

    def err(i, variant, message):
        errors.append({"index": i, "variant": str(variant), "message": message})

    is_count = metric not in AMOUNT_METRICS
    step = Decimal("1") if is_count else CENT
    variants = {TierVariant.NORMAL.value: [], TierVariant.AMERICAN.value: []}

    for i, t in normalized:
        v = t["variant"]
        if v not in variants:
            err(i, v, "Unknown variant.")
            continue
        if t["kind"] not in TierKind.values:
            err(i, v, "Unknown tier kind.")
        if t["min_value"] < 0:
            err(i, v, "Minimum must be 0 or more.")
        if t["value"] < 0:
            err(i, v, "Value must be 0 or more.")
        if t["kind"] == TierKind.PERCENT and t["value"] > 100:
            err(i, v, "Percent value cannot exceed 100.")
        if is_count:
            for bound in (t["min_value"], t["max_value"]):
                if bound is not None and bound != bound.to_integral_value():
                    err(i, v, "Bounds must be whole numbers for count metrics.")
                    break
        if t["max_value"] is not None and t["max_value"] < t["min_value"]:
            err(i, v, "Maximum must be at least the minimum.")
        variants[v].append((i, t))

    if not variants["normal"] and not any(e["message"] == "Unknown variant." for e in errors):
        err(0, "normal", "At least one normal tier is required.")
    if threshold is None and variants["american"]:
        for i, t in variants["american"]:
            err(i, "american", "American tiers require an American threshold.")
    if threshold is not None and not variants["american"]:
        err(0, "american", "At least one american tier is required when a threshold is set.")

    for v, items in variants.items():
        if len(items) > MAX_TIERS_PER_VARIANT:
            err(items[MAX_TIERS_PER_VARIANT][0], v, f"At most {MAX_TIERS_PER_VARIANT} tiers per variant.")
        items.sort(key=lambda p: p[1]["min_value"])
        for pos, (i, t) in enumerate(items):
            if pos == 0:
                continue
            pi, prev = items[pos - 1]
            if prev["max_value"] is None:
                err(pi, v, "Only the last tier may have no maximum.")
            elif t["min_value"] <= prev["max_value"]:
                err(i, v, "Tier overlaps the previous tier.")
            elif t["min_value"] != prev["max_value"] + step:
                err(i, v, "Gap between this tier and the previous tier.")

    if errors:
        raise PlanError("invalid_tiers", "Invalid tiers.", errors)

    result = []
    for v in variants:
        result.extend(t for _, t in variants[v])
    return result


def _q(amount):
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _pick_variant(value_share, threshold):
    if threshold is not None and value_share is not None and _dec(value_share) >= _dec(threshold):
        return TierVariant.AMERICAN.value
    return TierVariant.NORMAL.value


def evaluate_tiers(tiers, value, american_share=None, threshold=None):
    return _evaluate_variant(tiers, _dec(value), _pick_variant(american_share, threshold))


def _evaluate_variant(tiers, value, variant, rows=None):
    pairs = [(_normalize(t), r) for t, r in zip(tiers, rows or [None] * len(tiers))]
    pairs = [p for p in pairs if p[0]["variant"] == variant]
    pairs.sort(key=lambda p: p[0]["min_value"])
    sorted_rows = [p[1] for p in pairs]
    if not pairs or value < pairs[0][0]["min_value"]:
        return EvalResult(Decimal("0.00"), None, variant, sorted_rows)
    index = len(pairs) - 1  # above all tiers -> last
    for n, (t, _) in enumerate(pairs):
        if t["min_value"] <= value and (t["max_value"] is None or value <= t["max_value"]):
            index = n
            break
    t = pairs[index][0]
    if t["kind"] == TierKind.FLAT:
        amount = t["value"]
    elif t["kind"] == TierKind.UNIT:
        amount = t["value"] * value
    else:
        amount = t["value"] / 100 * value
    return EvalResult(_q(amount), index, variant, sorted_rows)


def evaluate(version, value, american_share=None):
    rows = list(version.tiers.all())
    tiers = [{"variant": r.variant, "min_value": r.min_value, "max_value": r.max_value,
              "kind": r.kind, "value": r.value} for r in rows]
    variant = _pick_variant(american_share, version.american_threshold_percent)
    return _evaluate_variant(tiers, _dec(value), variant, rows)


def month_start(d):
    return d.replace(day=1)


def version_for(plan, month):
    return (plan.versions.filter(effective_from__lte=month_start(month))
            .order_by("-effective_from").first())


def _active_plan_version(month, **target):
    from .models import CommissionPlan
    plan = CommissionPlan.objects.filter(is_active=True, **target).first()
    return version_for(plan, month) if plan else None


def personal_version_for(user, month, metric):
    version = _active_plan_version(month, kind=PlanKind.PERSONAL, user=user, metric=metric)
    if version is None and user.department_id:
        version = _active_plan_version(
            month, kind=PlanKind.PERSONAL, department_id=user.department_id, metric=metric)
    return version


def team_versions_for_leader(user, month, metric=None):
    from .models import CommissionPlan, Team
    extra = {} if metric is None else {"metric": metric}
    result = []
    for team in Team.objects.filter(leader=user, is_active=True).order_by("name"):
        plans = CommissionPlan.objects.filter(
            is_active=True, kind=PlanKind.TEAM, team=team, **extra).order_by("metric")
        for plan in plans:
            version = version_for(plan, month)
            if version is not None:
                result.append((team, version))
    return result


def team_total(team, values_by_user_id):
    ids = list(team.agents.values_list("pk", flat=True))
    if team.include_leader_in_total and team.leader_id:
        ids.append(team.leader_id)
    return sum((Decimal(values_by_user_id.get(i, 0)) for i in set(ids)), Decimal("0"))


def save_version(plan, month, tiers, by, *, threshold, today=None):
    from .models import PlanVersion, Tier
    month = month_start(month)
    if month < month_start(today or date.today()):
        raise PlanError("past_month", "Cannot change a plan for a past month.")
    normalized = validate_tiers(tiers, plan.metric, threshold)
    with transaction.atomic():
        version, created = PlanVersion.objects.get_or_create(
            plan=plan, effective_from=month,
            defaults={"created_by": by, "american_threshold_percent": threshold})
        if not created:
            version.tiers.all().delete()
            version.american_threshold_percent = threshold
            version.save(update_fields=["american_threshold_percent", "updated_at"])
        Tier.objects.bulk_create([Tier(version=version, **t) for t in normalized])
        if plan.kind == PlanKind.TEAM and plan.team.leader_id:
            notify([plan.team.leader],
                   f"The commission plan of team {plan.team.name} was updated ({month:%Y-%m}).",
                   kind=NotificationKinds.TEAM, title="Team plan",
                   link=f"/teams?tab=plans&plan={plan.uuid}", sender=by)
    return version


def set_members(team, add, remove, by):
    if {u.pk for u in add} & {u.pk for u in remove}:
        raise PlanError("invalid", "A user cannot be both added and removed.")
    if team.leader_id and any(u.pk == team.leader_id for u in add):
        raise PlanError("leader_is_agent", "The team leader cannot also be an agent.")
    with transaction.atomic():
        existing = set(team.agents.values_list("pk", flat=True))
        new_agents = [u for u in dict.fromkeys(add) if u.pk not in existing]
        team.agents.add(*add)
        team.agents.remove(*remove)
        if new_agents:
            notify(new_agents, f"You were added to team {team.name}.",
                   kind=NotificationKinds.TEAM, title="Team", link="/teams", sender=by)
    return team


def set_leader(team, user, by):
    with transaction.atomic():
        team.leader = user
        team.save(update_fields=["leader", "updated_at"])
        if user is not None:
            team.agents.remove(user)
    return team


def _check_name(name, department_id, exclude=None):
    from .models import Team
    clash = Team.objects.filter(
        department_id=department_id, is_active=True, name__iexact=name)
    if exclude is not None:
        clash = clash.exclude(pk=exclude.pk)
    if clash.exists():
        raise PlanError("duplicate_name", "An active team with this name already exists in the department.")


def create_team(name, department, leader, agents, include_leader_in_total, by):
    from .models import Team
    if leader is not None and any(u.pk == leader.pk for u in agents):
        raise PlanError("leader_is_agent", "The team leader cannot also be an agent.")
    _check_name(name, department.pk)
    with transaction.atomic():
        team = Team.objects.create(
            name=name, department=department, include_leader_in_total=include_leader_in_total)
        if leader is not None:
            set_leader(team, leader, by)
        if agents:
            set_members(team, list(agents), [], by)
    return team


def update_team(team, by, *, name=None, department=None, include_leader_in_total=None,
                set_leader_to=False, leader=None):
    """Apply a partial update; pass ``set_leader_to=True`` to change the leader (``leader`` may be None)."""
    new_name = team.name if name is None else name
    new_dept = team.department if department is None else department
    if (new_name != team.name or new_dept.pk != team.department_id) and team.is_active:
        _check_name(new_name, new_dept.pk, exclude=team)
    with transaction.atomic():
        team.name, team.department = new_name, new_dept
        if include_leader_in_total is not None:
            team.include_leader_in_total = include_leader_in_total
        team.save()
        if set_leader_to:
            set_leader(team, leader, by)
    return team
