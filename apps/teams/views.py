import re
import uuid as uuid_lib
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.users.models import Department, User
from apps.users.types import UserTypes

from .models import CommissionPlan, Team
from .permissions import (
    can_manage_department, can_manage_plan, can_manage_team, is_top, manageable_departments,
    visible_plans, visible_teams,
)
from .serializers import plan_data, team_data, version_data
from .services import (
    PlanError, create_team, evaluate_tiers, month_start, personal_version_for, save_version,
    set_members, team_versions_for_leader, update_team, validate_tiers, version_for,
)
from .types import PlanKind, PlanMetric

MAX_MEMBERS_PER_CALL = 200
MAX_TIERS_PER_CALL = 100
MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class _Invalid(Exception):
    pass


def _invalid(message: str) -> Response:
    return error(message, "invalid", 400)


def _not_found() -> Response:
    return error("Not found", "not_found", 404)


def _forbidden() -> Response:
    return error("You do not have permission to do that.", "forbidden", 403)


def _archived() -> Response:
    return error("This plan is archived.", "archived", 400)


def _uuid(value) -> Optional[uuid_lib.UUID]:
    try:
        return uuid_lib.UUID(str(value))
    except ValueError:
        return None


def _body(request) -> Optional[dict]:
    return request.data if isinstance(request.data, dict) else None


def _name(raw) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 100:
        raise _Invalid("name is required (max 100 characters).")
    return raw.strip()


def _department(raw) -> Department:
    uid = _uuid(raw)
    dept = Department.objects.filter(uuid=uid).first() if uid else None
    if dept is None:
        raise _Invalid("Invalid department.")
    return dept


def _user(raw, label="user") -> User:
    uid = _uuid(raw)
    user = User.objects.filter(uuid=uid, is_active=True).first() if uid else None
    if user is None:
        raise _Invalid(f"Invalid {label}.")
    return user


def _users(raw, label, *, active_only=True) -> list:
    if not isinstance(raw, list):
        raise _Invalid(f"'{label}' must be a list of user uuids.")
    if len(raw) > MAX_MEMBERS_PER_CALL:
        raise _Invalid(f"At most {MAX_MEMBERS_PER_CALL} users per call.")
    ids = [_uuid(r) for r in raw]
    if any(i is None for i in ids):
        raise _Invalid(f"'{label}' contains an invalid uuid.")
    qs = User.objects.filter(uuid__in=ids)
    if active_only:
        qs = qs.filter(is_active=True)
    users = list(qs)
    if len(users) != len(set(ids)):
        raise _Invalid(f"'{label}' contains an unknown or inactive user.")
    return users


def _bool(raw, field) -> bool:
    if not isinstance(raw, bool):
        raise _Invalid(f"'{field}' must be true or false.")
    return raw


def _get_team(request, uuid):
    return visible_teams(request.user).select_related("department", "leader").filter(uuid=uuid).first()


def _plan_error(e: PlanError) -> Response:
    resp = error(e.message, e.code, 400)
    if e.errors:
        resp.data["errors"] = e.errors
    return resp


def _month(raw) -> date:
    m = MONTH_RE.match(raw) if isinstance(raw, str) else None
    if not m:
        raise _Invalid("Month must be formatted YYYY-MM.")
    return date(int(m.group(1)), int(m.group(2)), 1)


def _number(raw, field) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str, Decimal)):
        raise _Invalid(f"'{field}' must be a number.")
    try:
        d = Decimal(str(raw).strip())
    except InvalidOperation:
        raise _Invalid(f"'{field}' must be a number.")
    if not d.is_finite() or d < 0:
        raise _Invalid(f"'{field}' must be a number of 0 or more.")
    return d


def _tiers(raw) -> list:
    if not isinstance(raw, list) or len(raw) > MAX_TIERS_PER_CALL:
        raise _Invalid(f"'tiers' must be a list of at most {MAX_TIERS_PER_CALL} tiers.")
    return raw


def _metric(raw) -> str:
    if raw not in PlanMetric.values:
        raise _Invalid("Invalid metric.")
    return raw


def _threshold(raw, metric) -> Optional[Decimal]:
    if raw in (None, ""):
        return None
    d = _number(raw, "american_threshold_percent")
    if d <= 0 or d > 100 or d != d.quantize(Decimal("0.01")):
        raise _Invalid("'american_threshold_percent' must be above 0 and at most 100 (2 decimals).")
    if metric != PlanMetric.LEAD_COUNT:
        raise _Invalid("An American threshold is only supported for the lead_count metric.")
    return d.quantize(Decimal("0.01"))


def _plan_threshold(plan, body, month) -> Optional[Decimal]:
    """Threshold from the body, else carried over from the version effective at ``month``."""
    if "american_threshold_percent" in body:
        raw = body["american_threshold_percent"]
    else:
        prior = version_for(plan, month)
        raw = prior.american_threshold_percent if prior is not None else None
    return _threshold(raw, plan.metric)


def _get_plan(request, uuid):
    return (visible_plans(request.user)
            .select_related("department", "user", "team").filter(uuid=uuid).first())


def _plan_target(body) -> tuple:
    """Returns (kind, target kwargs, department_id used for authorization)."""
    kind = body.get("kind")
    if kind not in PlanKind.values:
        raise _Invalid("Invalid kind.")
    given = [k for k in ("department", "user", "team") if body.get(k)]
    if kind == PlanKind.TEAM:
        if given != ["team"]:
            raise _Invalid("A team plan needs exactly a 'team'.")
        uid = _uuid(body["team"])
        team = Team.objects.filter(uuid=uid).first() if uid else None
        if team is None:
            raise _Invalid("Invalid team.")
        return kind, {"team": team}, team.department_id
    if given == ["department"]:
        dept = _department(body["department"])
        return kind, {"department": dept}, dept.pk
    if given == ["user"]:
        target = _user(body["user"])
        return kind, {"user": target}, target.department_id
    raise _Invalid("A personal plan needs exactly one of 'department' or 'user'.")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def plans(request):
    user, today = request.user, date.today()
    if request.method == "GET":
        params = request.query_params
        qs = visible_plans(user).select_related("department", "user", "team")
        privileged = is_top(user) or user.role == UserTypes.MANAGER
        if not (privileged and params.get("include_archived") in ("1", "true")):
            qs = qs.filter(is_active=True)
        if params.get("kind"):
            if params["kind"] not in PlanKind.values:
                return _invalid("Invalid kind.")
            qs = qs.filter(kind=params["kind"])
        if params.get("metric"):
            if params["metric"] not in PlanMetric.values:
                return _invalid("Invalid metric.")
            qs = qs.filter(metric=params["metric"])
        for field in ("department", "team", "user"):
            if params.get(field):
                uid = _uuid(params[field])
                if uid is None:
                    return _invalid(f"Invalid {field}.")
                qs = qs.filter(**{f"{field}__uuid": uid})
        return Response([plan_data(p, user, today) for p in qs.order_by("created_at")])

    body = _body(request)
    if body is None:
        return _invalid("Body must be an object.")
    try:
        kind, target, auth_dept_id = _plan_target(body)
        if not can_manage_department(user, auth_dept_id):
            return _forbidden()
        metric = _metric(body.get("metric"))
        threshold = _threshold(body.get("american_threshold_percent"), metric)
        effective_from = _month(body.get("effective_from"))
        tiers = _tiers(body.get("tiers"))
        try:
            with transaction.atomic():
                plan = CommissionPlan.objects.filter(metric=metric, **target).first()
                if plan is None:
                    plan = CommissionPlan.objects.create(kind=kind, metric=metric, **target)
                elif plan.is_active:
                    return error("This target already has a commission plan for this metric.", "duplicate_plan", 400)
                else:  # archived plan for this target: reactivate it
                    plan.is_active = True
                    plan.save(update_fields=["is_active", "updated_at"])
                save_version(plan, effective_from, tiers, user, threshold=threshold)
        except IntegrityError:
            return error("This target already has a commission plan for this metric.",
                         "duplicate_plan", 400)
    except _Invalid as e:
        return _invalid(str(e))
    except PlanError as e:
        return _plan_error(e)
    return Response(plan_data(plan, user, today), status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def plan_detail(request, uuid):
    user, today = request.user, date.today()
    plan = _get_plan(request, uuid)
    if plan is None:
        return _not_found()
    if request.method == "GET":
        return Response(plan_data(plan, user, today))
    if not can_manage_plan(user, plan):
        return _forbidden()
    if request.method == "DELETE":
        plan.is_active = False
        plan.save(update_fields=["is_active", "updated_at"])
        return Response(plan_data(plan, user, today))

    if not plan.is_active:
        return _archived()
    body = _body(request)
    if body is None:
        return _invalid("Body must be an object.")
    try:
        if "metric" in body:
            raise _Invalid("The metric of a plan cannot be changed.")
        if "american_threshold_percent" not in body:
            raise _Invalid("Nothing to update.")
        if "effective_from" not in body or "tiers" not in body:
            raise _Invalid("Changing the threshold requires 'effective_from' and 'tiers'.")
        effective_from = _month(body["effective_from"])
        threshold = _plan_threshold(plan, body, effective_from)
        tiers = _tiers(body["tiers"])
        save_version(plan, effective_from, tiers, user, threshold=threshold)
    except _Invalid as e:
        return _invalid(str(e))
    except PlanError as e:
        return _plan_error(e)
    return Response(plan_data(plan, user, today))


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def plan_version(request, uuid, month):
    user = request.user
    plan = _get_plan(request, uuid)
    if plan is None:
        return _not_found()
    if request.method == "PUT" and not can_manage_plan(user, plan):
        return _forbidden()
    if request.method == "PUT" and not plan.is_active:
        return _archived()
    try:
        month_date = _month(month)
        if request.method == "GET":
            version = version_for(plan, month_date)
            return Response(version_data(version)) if version else _not_found()
        body = _body(request)
        if body is None:
            return _invalid("Body must be an object.")
        if month_date < month_start(date.today()):
            raise PlanError("past_month", "Cannot change a plan for a past month.")
        threshold = _plan_threshold(plan, body, month_date)
        version = save_version(plan, month_date, _tiers(body.get("tiers")), user,
                               threshold=threshold)
    except _Invalid as e:
        return _invalid(str(e))
    except PlanError as e:
        return _plan_error(e)
    return Response(version_data(version))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def plan_preview(request):
    body = _body(request)
    if body is None:
        return _invalid("Body must be an object.")
    try:
        metric = _metric(body.get("metric"))
        threshold = _threshold(body.get("american_threshold_percent"), metric)
        tiers = _tiers(body.get("tiers"))
        value = _number(body.get("value"), "value")
        share = (_number(body["american_share"], "american_share")
                 if body.get("american_share") is not None else None)
        normalized = validate_tiers(tiers, metric, threshold)
        result = evaluate_tiers(normalized, value, share, threshold)
    except _Invalid as e:
        return _invalid(str(e))
    except PlanError as e:
        return _plan_error(e)
    return Response({"amount": str(result.amount), "tier_index": result.tier_index,
                     "variant": result.variant})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def teams(request):
    user = request.user
    if request.method == "GET":
        params = request.query_params
        qs = visible_teams(user).select_related("department", "leader")
        privileged = is_top(user) or user.role == UserTypes.MANAGER
        if not (privileged and params.get("include_archived") in ("1", "true")):
            qs = qs.filter(is_active=True)
        if params.get("department"):
            dept = _uuid(params["department"])
            if dept is None:
                return _invalid("Invalid department.")
            qs = qs.filter(department__uuid=dept)
        if v := params.get("search"):
            qs = qs.filter(Q(name__icontains=v) | Q(leader__first_name__icontains=v)
                           | Q(leader__last_name__icontains=v) | Q(leader__username__icontains=v))
        return Response([team_data(t, user) for t in qs.order_by("name")])

    body = _body(request)
    if body is None:
        return _invalid("Body must be an object.")
    try:
        name = _name(body.get("name"))
        dept = _department(body.get("department"))
        if not can_manage_department(user, dept.pk):
            return _forbidden()
        leader = _user(body["leader"], "leader") if body.get("leader") else None
        agents = _users(body.get("agents", []), "agents")
        include = _bool(body.get("include_leader_in_total", False), "include_leader_in_total")
        team = create_team(name, dept, leader, agents, include, user)
    except _Invalid as e:
        return _invalid(str(e))
    except PlanError as e:
        return error(e.message, e.code, 400)
    return Response(team_data(team, user), status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def team_detail(request, uuid):
    user = request.user
    team = _get_team(request, uuid)
    if team is None:
        return _not_found()
    if request.method == "GET":
        return Response(team_data(team, user))
    if not can_manage_team(user, team):
        return _forbidden()
    if request.method == "DELETE":
        with transaction.atomic():
            team.is_active = False
            team.save(update_fields=["is_active", "updated_at"])
            CommissionPlan.objects.filter(team=team).update(is_active=False)
        return Response(team_data(team, user))

    body = _body(request)
    if body is None:
        return _invalid("Body must be an object.")
    try:
        kwargs = {}
        if "name" in body:
            kwargs["name"] = _name(body["name"])
        if "department" in body:
            dept = _department(body["department"])
            if not can_manage_department(user, dept.pk):
                return _forbidden()
            kwargs["department"] = dept
        if "include_leader_in_total" in body:
            kwargs["include_leader_in_total"] = _bool(
                body["include_leader_in_total"], "include_leader_in_total")
        if "leader" in body:
            kwargs["set_leader_to"] = True
            kwargs["leader"] = (None if body["leader"] is None
                                else _user(body["leader"], "leader"))
        team = update_team(team, user, **kwargs)
    except _Invalid as e:
        return _invalid(str(e))
    except PlanError as e:
        return error(e.message, e.code, 400)
    return Response(team_data(team, user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def team_members(request, uuid):
    user = request.user
    team = _get_team(request, uuid)
    if team is None:
        return _not_found()
    if not can_manage_team(user, team):
        return _forbidden()
    body = _body(request)
    if body is None:
        return _invalid("Body must be an object.")
    try:
        add = _users(body.get("add", []), "add")
        remove = _users(body.get("remove", []), "remove", active_only=False)
        if len(add) + len(remove) > MAX_MEMBERS_PER_CALL:
            raise _Invalid(f"At most {MAX_MEMBERS_PER_CALL} users per call.")
        team = set_members(team, add, remove, user)
    except _Invalid as e:
        return _invalid(str(e))
    except PlanError as e:
        return error(e.message, e.code, 400)
    return Response(team_data(team, user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def meta(request):
    depts = manageable_departments(request.user).order_by("name")
    return Response({
        "can_manage": is_top(request.user) or depts.exists(),
        "manageable_departments": [{"uuid": str(d.uuid), "name": d.name} for d in depts],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my(request):
    user, today = request.user, date.today()
    active = visible_teams(user).filter(is_active=True).select_related("department", "leader")
    led = active.filter(leader=user).order_by("name")
    member = active.filter(agents=user).order_by("name")
    personal = [v for m in PlanMetric.values if (v := personal_version_for(user, today, m))]
    return Response({
        "teams_led": [team_data(t, user) for t in led],
        "teams_member": [team_data(t, user) for t in member],
        "personal_plans": [plan_data(v.plan, user, today) for v in personal],
        "team_plans": [plan_data(v.plan, user, today) for _, v in team_versions_for_leader(user, today)],
    })
