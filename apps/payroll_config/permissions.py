from apps.attendance.permissions import is_hr_plus
from apps.users.admin_permissions import can_manage_user, is_top
from apps.users.types import UserTypes


def can_view_salary(viewer, user) -> bool:
    return viewer.pk == user.pk or can_manage_user(viewer, user)


def can_edit_salary(viewer, user) -> bool:
    return can_manage_user(viewer, user) and (viewer.pk != user.pk or is_top(viewer))


def can_view_rates(viewer) -> bool:
    return is_hr_plus(viewer) or viewer.role == UserTypes.MANAGER


def can_edit_rates(viewer) -> bool:
    return is_hr_plus(viewer)
