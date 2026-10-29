import uuid as uuid_lib
from datetime import date
from typing import Optional

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.users.models import Department, User
from apps.users.types import UserTypes

from .permissions import (
    can_manage_department, can_manage_team, is_top, manageable_departments,
    visible_teams,
)
from .serializers import plan_data, team_data
from .services import (
    PlanError, create_team, personal_version_for, set_members, team_versions_for_leader,
    update_team,
)

MAX_MEMBERS_PER_CALL = 200


class _Invalid(Exception):
    pass


def _invalid(message: str) -> Response:
    return error(message, "invalid", 400)


def _not_found() -> Response:
    return error("Not found", "not_found", 404)


def _forbidden() -> Response:
    return error("You do not have permission to do that.", "forbidden", 403)


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
        team.is_active = False
        team.save(update_fields=["is_active", "updated_at"])
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
            kwargs["leader"] = _user(body["leader"], "leader") if body["leader"] else None
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
    personal = personal_version_for(user, today)
    return Response({
        "teams_led": [team_data(t, user) for t in led],
        "teams_member": [team_data(t, user) for t in member],
        "personal_plan": plan_data(personal.plan, user, today) if personal else None,
        "team_plans": [plan_data(v.plan, user, today) for _, v in team_versions_for_leader(user, today)],
    })
