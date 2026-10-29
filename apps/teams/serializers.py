from .models import CommissionPlan, Team
from .permissions import can_manage_plan, can_manage_team
from .services import version_for


def user_name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def user_brief(user) -> dict:
    return {"uuid": str(user.uuid), "name": user_name(user)}


def tier_data(tier) -> dict:
    return {
        "variant": tier.variant,
        "min_value": str(tier.min_value),
        "max_value": None if tier.max_value is None else str(tier.max_value),
        "kind": tier.kind,
        "value": str(tier.value),
    }


def team_data(team, viewer) -> dict:
    return {
        "uuid": str(team.uuid),
        "name": team.name,
        "department": {"uuid": str(team.department.uuid), "name": team.department.name},
        "leader": user_brief(team.leader) if team.leader else None,
        "agents": [user_brief(u) for u in team.agents.order_by("first_name", "last_name", "username")],
        "include_leader_in_total": team.include_leader_in_total,
        "is_active": team.is_active,
        "has_plan": CommissionPlan.objects.filter(team=team, is_active=True).exists(),
        "can_edit": can_manage_team(viewer, team),
    }


def _target(plan) -> dict:
    if plan.department_id:
        return {"type": "department", "uuid": str(plan.department.uuid), "name": plan.department.name}
    if plan.user_id:
        return {"type": "user", "uuid": str(plan.user.uuid), "name": user_name(plan.user)}
    return {"type": "team", "uuid": str(plan.team.uuid), "name": plan.team.name}


def _threshold(version):
    value = version.american_threshold_percent
    return None if value is None else str(value)


def version_data(version) -> dict:
    return {"effective_from": f"{version.effective_from:%Y-%m}",
            "metric": version.plan.metric,
            "american_threshold_percent": _threshold(version),
            "tiers": [tier_data(t) for t in version.tiers.all()]}


def plan_data(plan, viewer, month) -> dict:
    current = version_for(plan, month)
    return {
        "uuid": str(plan.uuid),
        "kind": plan.kind,
        "target": _target(plan),
        "metric": plan.metric,
        "american_threshold_percent": _threshold(current) if current else None,
        "is_active": plan.is_active,
        "current_version": version_data(current) if current else None,
        "versions": [f"{d:%Y-%m}" for d in
                     plan.versions.order_by("-effective_from").values_list("effective_from", flat=True)],
        "can_edit": can_manage_plan(viewer, plan),
    }
