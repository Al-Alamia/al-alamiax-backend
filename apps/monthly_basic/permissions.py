from apps.attendance.permissions import is_hr_plus, is_manager_of
from apps.users.admin_permissions import can_manage_user, is_top
from apps.users.models import User
from apps.users.types import UserTypes

from .types import BasicStatus


def can_manage_basic(viewer, target) -> bool:
    return bool(can_manage_user(viewer, target)
                or (is_manager_of(viewer, target) and not target.is_superuser
                    and target.role != UserTypes.OWNER))


def can_edit_basic(viewer, target) -> bool:
    return can_manage_basic(viewer, target) and (viewer.pk != target.pk or is_top(viewer))


def can_view_basic(viewer, target, record) -> bool:
    return can_manage_basic(viewer, target) or bool(
        viewer.pk == target.pk and record is not None and record.status == BasicStatus.GIVEN)


def list_scope(viewer):
    """Users whose records ``viewer`` may list; None when listing is not allowed."""
    if is_hr_plus(viewer):
        return _hr_scope(viewer)
    if viewer.role == UserTypes.MANAGER and viewer.department_id is not None:
        return User.objects.filter(is_active=True, department_id=viewer.department_id,
                                   is_superuser=False).exclude(role=UserTypes.OWNER)
    return None


def _hr_scope(viewer):
    qs = User.objects.filter(is_active=True)
    if not viewer.is_superuser:
        qs = qs.exclude(is_superuser=True)
    if not is_top(viewer):
        qs = qs.exclude(role=UserTypes.OWNER)
    return qs
