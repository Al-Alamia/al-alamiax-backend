from django.db.models import Q

from apps.attendance.permissions import can_view, is_hr_plus, is_manager_of  # noqa: F401 (can_view re-exported)
from apps.users.models import User
from apps.users.types import UserTypes

from .models import Penalty


def is_top(user) -> bool:
    return bool(user.is_superuser or user.role == UserTypes.OWNER)


def can_penalize(viewer, target) -> bool:
    return bool(target.is_active and (viewer.pk != target.pk or is_top(viewer))
                and (is_hr_plus(viewer) or is_manager_of(viewer, target)))


def can_void(viewer, penalty) -> bool:
    if penalty.is_voided or (penalty.user_id == viewer.pk and not is_top(viewer)):
        return False
    return is_hr_plus(viewer) or (
        penalty.created_by_id == viewer.pk and can_penalize(viewer, penalty.user))


def can_add(viewer) -> bool:
    return is_hr_plus(viewer) or (viewer.role == UserTypes.MANAGER and viewer.department_id is not None)


def can_manage_types(viewer) -> bool:
    return is_hr_plus(viewer)


def visible_penalties(viewer):
    """Penalties ``viewer`` may see; includes those of deactivated users (history stays visible)."""
    if is_hr_plus(viewer):
        return Penalty.objects.all()
    if viewer.role == UserTypes.MANAGER and viewer.department_id is not None:
        return Penalty.objects.filter(
            Q(user=viewer) | Q(user__department_id=viewer.department_id))
    return Penalty.objects.filter(user=viewer)


def penalty_targets(viewer):
    """Active users for whom ``can_penalize(viewer, user)`` holds."""
    active = User.objects.filter(is_active=True)
    if is_hr_plus(viewer):
        return active if is_top(viewer) else active.exclude(pk=viewer.pk)
    if viewer.role == UserTypes.MANAGER and viewer.department_id is not None:
        return active.filter(department_id=viewer.department_id).exclude(pk=viewer.pk)
    return User.objects.none()
