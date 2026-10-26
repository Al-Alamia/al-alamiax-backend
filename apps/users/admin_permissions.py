from apps.attendance.permissions import is_hr_plus, is_manager_of
from apps.users.models import User
from apps.users.types import UserTypes

MAX_DEVICE_APPROVERS = 20


def is_top(user) -> bool:
    return bool(user.is_superuser or user.role == UserTypes.OWNER)


def _hidden_from(viewer, target) -> bool:
    return bool((target.is_superuser and not viewer.is_superuser)
                or (target.role == UserTypes.OWNER and not is_top(viewer)))


def visible_users(viewer):
    """Users ``viewer`` may list (agents get none)."""
    if is_hr_plus(viewer):
        qs = User.objects.all()
    elif viewer.role == UserTypes.MANAGER and viewer.department_id is not None:
        qs = User.objects.filter(department_id=viewer.department_id)
    else:
        return User.objects.none()
    if not viewer.is_superuser:
        qs = qs.exclude(is_superuser=True)
    if not is_top(viewer):
        qs = qs.exclude(role=UserTypes.OWNER)
    return qs


def can_view_user(viewer, target) -> bool:
    return viewer.pk == target.pk or (
        not _hidden_from(viewer, target) and (is_hr_plus(viewer) or is_manager_of(viewer, target)))


def assignable_roles(viewer) -> list:
    if not is_hr_plus(viewer):
        return []
    roles = [UserTypes.AGENT, UserTypes.MANAGER, UserTypes.HR]
    if is_top(viewer):
        roles.append(UserTypes.OWNER)
    return roles


def can_manage_user(viewer, target) -> bool:
    return bool(is_hr_plus(viewer) and not _hidden_from(viewer, target)
                and (target.role != UserTypes.OWNER or is_top(viewer)))


def can_manage_devices(viewer, target) -> bool:
    return bool((viewer.pk != target.pk or is_top(viewer))
                and (can_manage_user(viewer, target)
                     or (is_manager_of(viewer, target) and target.is_active)))


def can_view_devices(viewer, target) -> bool:
    return viewer.pk == target.pk or can_manage_devices(viewer, target)


def can_view_files(viewer, target) -> bool:
    return can_view_user(viewer, target)


def can_manage_files(viewer, target) -> bool:
    return can_manage_user(viewer, target)


def can_view_history(viewer, target) -> bool:
    return bool(is_hr_plus(viewer) and not _hidden_from(viewer, target))


def device_approvers(target) -> list:
    """Active HR/OWNER users then active managers of the target's department (max 20)."""
    top = list(User.objects.filter(is_active=True, role__in=[UserTypes.HR, UserTypes.OWNER])
               .exclude(pk=target.pk).order_by("username")[:MAX_DEVICE_APPROVERS])
    managers = []
    if target.department_id is not None:
        managers = list(User.objects.filter(
            is_active=True, role=UserTypes.MANAGER, department_id=target.department_id)
            .exclude(pk=target.pk).order_by("username")[:MAX_DEVICE_APPROVERS])
    return (top + managers)[:MAX_DEVICE_APPROVERS]
