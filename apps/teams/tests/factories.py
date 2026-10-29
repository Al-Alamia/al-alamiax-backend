from apps.teams.models import CommissionPlan, PlanVersion, Team, Tier
from apps.teams.types import PlanKind


def make_team(department, name="T", leader=None, agents=()):
    team = Team.objects.create(name=name, department=department, leader=leader)
    if agents:
        team.agents.set(agents)
    return team


def make_plan(kind, *, department=None, user=None, team=None):
    return CommissionPlan.objects.create(kind=kind, department=department, user=user, team=team)


def make_version(plan, month, tiers, metric="lead_count", threshold=None):
    version = PlanVersion.objects.create(
        plan=plan, effective_from=month, metric=metric, american_threshold_percent=threshold)
    for t in tiers:
        Tier.objects.create(
            version=version, variant=t.get("variant", "normal"),
            min_value=t["min_value"], max_value=t.get("max_value"),
            kind=t["kind"], value=t["value"],
        )
    return version
