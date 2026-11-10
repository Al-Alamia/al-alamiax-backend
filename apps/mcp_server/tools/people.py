import re
import uuid as uuid_lib
from datetime import date
from decimal import Decimal

from django.db.models import Q

from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.mcp_server.tools.common import limit_schema, list_result, user_brief
from apps.monthly_basic.services import period_bounds
from apps.salaries.metrics import metric_values
from apps.teams.models import CommissionPlan, Team
from apps.teams.permissions import list_teams_queryset, supervised_users, visible_teams
from apps.teams.serializers import tier_data
from apps.teams.services import (
    evaluate, personal_version_for, team_total, team_versions_for_leader, version_for)
from apps.teams.types import PlanKind, PlanMetric
from apps.users.admin_permissions import can_view_user, visible_users
from apps.users.models import User
from apps.users.types import UserTypes

MONTH_PATTERN = r"\d{4}-(0[1-9]|1[0-2])"


def _uuid(raw):
    try:
        return uuid_lib.UUID(str(raw))
    except ValueError:
        return None


def _user_item(u):
    data = user_brief(u)
    data["is_active"] = u.is_active
    return data


def _team_refs(user):
    teams = Team.objects.filter(Q(leader=user) | Q(agents=user), is_active=True).distinct().order_by("name")
    return [{"uuid": str(t.pk), "name": t.name} for t in teams]


@tool("search_users", title="Search users",
      description="Search users you are allowed to see (by name, username or email), optionally "
                  "filtered by department (name or uuid), role and active state.",
      schema={"type": "object", "properties": {
          "query": {"type": "string", "maxLength": 100},
          "department": {"type": "string", "maxLength": 100},
          "role": {"type": "string", "enum": [r.value for r in UserTypes]},
          "active": {"type": "boolean", "default": True},
          "limit": limit_schema()}})
def search_users(user, args):
    qs = visible_users(user).select_related("department").filter(is_active=args["active"])
    if q := args.get("query", "").strip():
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q)
                       | Q(last_name__icontains=q) | Q(email__icontains=q))
    if dept := args.get("department", "").strip():
        uid = _uuid(dept)
        qs = qs.filter(department__uuid=uid) if uid else qs.filter(department__name__icontains=dept)
    if args.get("role"):
        qs = qs.filter(role=args["role"])
    qs = qs.order_by("username")[:args["limit"] + 1]
    result = list_result(qs, _user_item, args["limit"])
    return "%d users%s" % (result["count"], " (truncated)" if result["truncated"] else ""), result


@tool("get_user", title="Get user",
      description="Profile basics, department, role and teams of one user you are allowed to see.",
      schema={"type": "object", "required": ["user_uuid"], "properties": {
          "user_uuid": {"type": "string", "format": "uuid"}}})
def get_user(user, args):
    target = (User.objects.select_related("department", "profile")
              .filter(pk=args["user_uuid"]).first())
    if target is None or not can_view_user(user, target):
        raise ToolError("User not found", "not_found")
    data = _user_item(target)
    profile = getattr(target, "profile", None)
    data["phone"] = profile.phone if profile else None
    data["teams"] = _team_refs(target)
    return "User %s" % target.username, data


def _team_item(t):
    return {"uuid": str(t.pk), "name": t.name,
            "department": t.department.name,
            "leader": user_brief(t.leader) if t.leader else None,
            "member_count": t.agents.count(), "is_active": t.is_active}


@tool("list_teams", title="List teams",
      description="Active teams you can see, optionally filtered by department uuid.",
      schema={"type": "object", "properties": {
          "department": {"type": "string", "maxLength": 100,
                         "description": "Department name or uuid"},
          "limit": limit_schema()}})
def list_teams(user, args):
    dept_uuid, dept_name = None, ""
    if dept := args.get("department", "").strip():
        dept_uuid = _uuid(dept)
        dept_name = "" if dept_uuid else dept
    qs = list_teams_queryset(user, department_uuid=dept_uuid)
    if dept_name:
        qs = qs.filter(department__name__icontains=dept_name)
    qs = qs.select_related("leader__department").order_by("name")[:args["limit"] + 1]
    result = list_result(qs, _team_item, args["limit"])
    return "%d teams%s" % (result["count"], " (truncated)" if result["truncated"] else ""), result


def _visible_team(user, team_uuid):
    team = (visible_teams(user).select_related("department", "leader")
            .filter(pk=team_uuid).first())
    if team is None:
        raise ToolError("Team not found", "not_found")
    return team


@tool("get_team", title="Get team",
      description="Members, leader, department and current-month commission plans of a team you can see.",
      schema={"type": "object", "required": ["team_uuid"], "properties": {
          "team_uuid": {"type": "string", "format": "uuid"}}})
def get_team(user, args):
    team = _visible_team(user, args["team_uuid"])
    today = date.today()
    plans = []
    for plan in CommissionPlan.objects.filter(team=team, is_active=True).order_by("metric"):
        version = version_for(plan, today)
        if version is not None:
            plans.append({"metric": plan.metric,
                          "effective_from": "%s" % version.effective_from.strftime("%Y-%m"),
                          "american_threshold_percent": (None if version.american_threshold_percent is None
                                                         else str(version.american_threshold_percent)),
                          "tiers": version.tiers.count()})
    members = team.agents.select_related("department").order_by("username")
    data = {"uuid": str(team.pk), "name": team.name, "is_active": team.is_active,
            "department": {"uuid": str(team.department.pk), "name": team.department.name},
            "leader": user_brief(team.leader) if team.leader else None,
            "include_leader_in_total": team.include_leader_in_total,
            "members": [user_brief(m) for m in members],
            "plans": plans}
    return "Team %s with %d members" % (team.name, len(data["members"])), data


def _progress_row(metric, version, value, share):
    result = evaluate(version, value, share)
    tiers = result._tiers
    if result.tier_index is None:
        nxt = tiers[0] if tiers else None
    else:
        nxt = tiers[result.tier_index + 1] if result.tier_index + 1 < len(tiers) else None
    threshold = version.american_threshold_percent
    return {"metric": metric,
            "value": str(value),
            "american_share": None if share is None else str(round(Decimal(share), 2)),
            "american_threshold_percent": None if threshold is None else str(threshold),
            "variant": result.variant,
            "amount": str(result.amount),
            "tier_reached": tier_data(result.tier) if result.tier is not None else None,
            "next_tier": tier_data(nxt) if nxt is not None else None}


def _personal_progress(target, month, start, end):
    mine = metric_values(target, start, end)
    rows = []
    for metric in PlanMetric.values:
        version = personal_version_for(target, month, metric)
        if version is not None:
            rows.append(_progress_row(metric, version, mine["values"][metric], mine["shares"][metric]))
    return rows


def _team_progress(team, month, start, end):
    members = list(team.agents.all())
    if team.include_leader_in_total and team.leader_id:
        members.append(team.leader)
    mvs = {m.pk: metric_values(m, start, end) for m in members}
    rows = []
    for plan in CommissionPlan.objects.filter(
            is_active=True, kind=PlanKind.TEAM, team=team).order_by("metric"):
        version = version_for(plan, month)
        if version is None:
            continue
        metric = plan.metric
        total = team_total(team, {pk: mv["values"][metric] for pk, mv in mvs.items()})
        numerators = sum((mv["shares"][metric] * mv["values"][metric] / 100
                          for mv in mvs.values() if mv["shares"][metric] is not None), Decimal("0"))
        share = None
        if total and metric not in ("sales_american_amount", "american_subscription_count"):
            share = numerators * 100 / total
        rows.append(_progress_row(metric, version, total, share))
    return rows


@tool("get_target_progress", title="Get target progress",
      description="Progress towards commission targets for a user (personal plans) or a team "
                  "(team plans) in a month: metric value, threshold, tier reached and next tier. "
                  "Give exactly one of user_uuid or team_uuid.",
      schema={"type": "object", "properties": {
          "user_uuid": {"type": "string", "format": "uuid"},
          "team_uuid": {"type": "string", "format": "uuid"},
          "month": {"type": "string", "pattern": MONTH_PATTERN,
                    "description": "YYYY-MM, defaults to the current month"}}})
def get_target_progress(user, args):
    if ("user_uuid" in args) == ("team_uuid" in args):
        raise ToolError("Provide exactly one of user_uuid or team_uuid", "invalid_arguments")
    key = args.get("month") or date.today().strftime("%Y-%m")
    month = date(int(key[:4]), int(key[5:7]), 1)
    start, end = period_bounds(key)
    if "user_uuid" in args:
        target = supervised_users(user).filter(pk=args["user_uuid"]).first()
        if target is None and args["user_uuid"] == user.pk:
            target = user
        if target is None:
            raise ToolError("User not found", "not_found")
        rows = _personal_progress(target, month, start, end)
        label = target.username
    else:
        team = _visible_team(user, args["team_uuid"])
        rows = _team_progress(team, month, start, end)
        label = team.name
    return ("%d targets for %s in %s" % (len(rows), label, key)), {
        "month": key, "period": {"start": str(start), "end": str(end)}, "progress": rows}
