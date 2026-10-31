from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.services import month_of, period_bounds
from apps.monthly_basic.types import BasicStatus
from apps.payroll_config.services import MissingRate, daily_bonus, rate_for, rates_for
from apps.teams.services import evaluate, personal_version_for, team_total, team_versions_for_leader
from apps.teams.types import AMOUNT_METRICS, PlanMetric

from .metrics import metric_values
from .models import Salary
from .types import PartKind, SalaryStatus

CENT = Decimal("0.01")
ZERO = Decimal("0")


class SalaryError(Exception):
    def __init__(self, type, message):
        super().__init__(message)
        self.type = type
        self.message = message

    @property
    def status(self):
        return {"forbidden": 403, "not_found": 404}.get(self.type, 400)


def _q(d) -> Decimal:
    return Decimal(d).quantize(CENT, rounding=ROUND_HALF_UP)


def _money(d) -> str:
    return f"{_q(d):.2f}"


def _count(d) -> str:
    return str(int(Decimal(d)))


def _share_str(share) -> Optional[str]:
    return None if share is None else _money(share)


def _user_ref(user):
    if user is None:
        return None
    return {"uuid": str(user.uuid), "name": user.get_full_name() or user.username}


def _tier(result) -> Optional[dict]:
    if result.tier_index is None:
        return None
    t = result.tier
    return {
        "index": result.tier_index,
        "min_value": str(t.min_value),
        "max_value": None if t.max_value is None else str(t.max_value),
        "kind": t.kind,
        "value": str(t.value),
    }


def _given_result(salary) -> dict:
    return {
        "basic": {"net": None if salary.basic_net is None else _money(salary.basic_net),
                  "status": SalaryStatus.GIVEN.value},
        "parts": salary.parts or [],
        "commission": _money(salary.commission or ZERO),
        "total": None if salary.total is None else _money(salary.total),
        "errors": [],
    }


def _base_part(key, kind, label, metric, team=None):
    return {
        "key": key, "kind": kind, "label": label, "metric": metric, "team": team,
        "value": "0", "american_share": None, "variant": None, "tier": None,
        "currency": "EGP", "rate": None, "computed": "0.00", "override": None, "amount": "0.00",
    }


def _tier_part(part, metric, version, value, share, month, errors):
    """Fill a tier-based part; amount metrics are converted from SAR to EGP."""
    result = evaluate(version, value, share)
    part["american_share"] = _share_str(share)
    part["variant"] = result.variant
    part["tier"] = _tier(result)
    amount = result.amount
    if metric in AMOUNT_METRICS:
        part["value"] = _money(value)
        part["currency"] = "SAR"
        try:
            rate = rate_for(month, "SAR")
        except MissingRate as e:
            errors.append(e)
            amount = ZERO
        else:
            part["rate"] = str(rate)
            amount = _q(amount * rate)
    else:
        part["value"] = _count(value)
    part["computed"] = _money(amount)


def _team_part(team, version, month, start, end, cache, errors):
    metric = version.plan.metric
    part = _base_part(f"{PartKind.TEAM.value}:{team.uuid}:{metric}", PartKind.TEAM.value,
                      f"Team {team.name} ({PlanMetric(metric).label})", metric,
                      {"uuid": str(team.uuid), "name": team.name})
    members = list(team.agents.all())
    if team.include_leader_in_total and team.leader_id:
        members.append(team.leader)
    values, numerators = {}, ZERO
    failed = False
    for m in members:
        if m.pk not in cache:
            try:
                cache[m.pk] = metric_values(m, start, end)
            except MissingRate as e:
                cache[m.pk] = e
        mv = cache[m.pk]
        if isinstance(mv, MissingRate):
            errors.append(mv)
            failed = True
            continue
        values[m.pk] = mv["values"][metric]
        share = mv["shares"][metric]
        if share is not None:
            numerators += share * mv["values"][metric] / 100
    if failed:
        part["value"] = _money(ZERO) if metric in AMOUNT_METRICS else "0"
        if metric in AMOUNT_METRICS:
            part["currency"] = "SAR"
        return part
    total = team_total(team, values)
    share = None
    if total and metric not in ("sales_american_amount", "american_subscription_count"):
        share = numerators * 100 / total
    _tier_part(part, metric, version, total, share, month, errors)
    return part


def _apply_overrides(parts, salary):
    overrides = {}
    if salary is not None:
        overrides = {o.part_key: o for o in salary.overrides.select_related("by")}
    for part in parts:
        o = overrides.get(part["key"])
        if o is None:
            part["amount"] = part["computed"]
            continue
        part["override"] = {"value": _money(o.value), "reason": o.reason,
                            "by": _user_ref(o.by), "at": o.updated_at.isoformat()}
        part["amount"] = _money(o.value)


def _error_dicts(errors, basic_given):
    out, seen = [], set()
    if not basic_given:
        out.append({"type": "basic_not_given"})
    for e in errors:
        key = (e.month, e.currency)
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": "missing_rate", "month": f"{e.month:%Y-%m}", "currency": e.currency})
    return out


def compute(user, period: str) -> dict:
    salary = (Salary.objects.filter(user=user, period=period).first())
    if salary is not None and salary.status == SalaryStatus.GIVEN:
        return _given_result(salary)

    start, end = period_bounds(period)
    month = month_of(period)
    basic = MonthlyBasic.objects.filter(user=user, period=period, status=BasicStatus.GIVEN).first()
    errors = []
    parts = []

    try:
        mine = metric_values(user, start, end)
    except MissingRate as e:
        errors.append(e)
        mine = None

    if mine is not None:
        for metric in PlanMetric:
            version = personal_version_for(user, month, metric.value)
            if version is None:
                continue
            part = _base_part(f"{PartKind.PERSONAL.value}:{metric.value}", PartKind.PERSONAL.value,
                              f"Personal target ({metric.label})", metric.value)
            _tier_part(part, metric.value, version, mine["values"][metric.value],
                       mine["shares"][metric.value], month, errors)
            parts.append(part)

        cache = {user.pk: mine}
        for team, version in team_versions_for_leader(user, month):
            parts.append(_team_part(team, version, month, start, end, cache, errors))

        rates = rates_for(user.department, month) if user.department_id else None
        if rates is not None:
            bonuses = [daily_bonus(rates, n) for n in mine["leads_by_day"].values()]
            part = _base_part(PartKind.DAILY_BONUS.value, PartKind.DAILY_BONUS.value,
                              "Daily bonus", None)
            part["value"] = str(sum(1 for b in bonuses if b > 0))
            part["computed"] = _money(sum(bonuses, ZERO))
            parts.append(part)
            part = _base_part(PartKind.AMERICAN_LEADS.value, PartKind.AMERICAN_LEADS.value,
                              "American leads", None)
            part["value"] = str(mine["american_lead_count"])
            part["computed"] = _money(mine["american_lead_count"] * rates.american_lead_price)
            parts.append(part)

    _apply_overrides(parts, salary)
    commission = sum((Decimal(p["amount"]) for p in parts), ZERO)
    net = None if basic is None else _q(basic.net)
    return {
        "basic": {"net": None if net is None else _money(net), "status": SalaryStatus.DRAFT.value},
        "parts": parts,
        "commission": _money(commission),
        "total": None if net is None else _money(net + commission),
        "errors": _error_dicts(errors, basic is not None),
    }
