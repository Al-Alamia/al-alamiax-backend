from apps.attendance.permissions import is_hr_plus
from apps.users.types import UserTypes


def is_top(user) -> bool:
    return bool(user.is_superuser or user.role == UserTypes.OWNER)


def can_view_salary(viewer, user) -> bool:
    return is_hr_plus(viewer) or viewer.pk == user.pk


def can_edit_salary(viewer, user) -> bool:
    return is_hr_plus(viewer) and (viewer.pk != user.pk or is_top(viewer))


def can_view_rates(viewer) -> bool:
    return is_hr_plus(viewer) or viewer.role == UserTypes.MANAGER


def can_edit_rates(viewer) -> bool:
    return is_hr_plus(viewer)
