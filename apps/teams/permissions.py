from django.db.models import Q

from apps.users.models import Department
from apps.users.types import UserTypes

from .models import CommissionPlan, Team


def is_top(user) -> bool:
    return bool(user.is_superuser or user.role == UserTypes.OWNER)


def can_read_all(user) -> bool:
    return is_top(user) or user.role == UserTypes.HR


def _manager_department_id(user):
    return user.department_id if user.role == UserTypes.MANAGER else None


def can_manage_department(user, department_id) -> bool:
    if is_top(user):
        return True
    return department_id is not None and _manager_department_id(user) == department_id


def can_manage_team(user, team) -> bool:
    return can_manage_department(user, team.department_id)


def _plan_department_id(plan):
    if plan.department_id:
        return plan.department_id
    if plan.user_id:
        return plan.user.department_id
    if plan.team_id:
        return plan.team.department_id
    return None


def can_manage_plan(user, plan) -> bool:
    return can_manage_department(user, _plan_department_id(plan))


def manageable_departments(user):
    if is_top(user):
        return Department.objects.all()
    dept_id = _manager_department_id(user)
    return Department.objects.filter(pk=dept_id) if dept_id else Department.objects.none()


def visible_teams(user):
    if can_read_all(user):
        return Team.objects.all()
    q = Q(leader=user) | Q(agents=user)
    if dept_id := _manager_department_id(user):
        q |= Q(department_id=dept_id)
    return Team.objects.filter(q).distinct()


def visible_plans(user):
    if can_read_all(user):
        return CommissionPlan.objects.all()
    q = (Q(user=user) | Q(team__leader=user))
    if user.department_id:
        q |= Q(department_id=user.department_id)
    if dept_id := _manager_department_id(user):
        q |= (Q(department_id=dept_id) | Q(user__department_id=dept_id)
              | Q(team__department_id=dept_id))
    return CommissionPlan.objects.filter(q).distinct()
