from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from apps.users.models import User
from apps.users.types import UserTypes


def is_hr_plus(user) -> bool:
    return bool(user.is_superuser or user.role in (UserTypes.HR, UserTypes.OWNER))


def _is_manager_of(viewer, target) -> bool:
    return (viewer.role == UserTypes.MANAGER and viewer.department_id is not None
            and viewer.department_id == target.department_id)


def scoped_users(user):
    """Active users whose attendance ``user`` may see."""
    active = User.objects.filter(is_active=True)
    if is_hr_plus(user):
        return active
    if user.role == UserTypes.MANAGER and user.department_id is not None:
        return active.filter(department_id=user.department_id)
    return active.filter(pk=user.pk)


def can_view(viewer, target) -> bool:
    """Deliberately ignores ``is_active``: HR and managers may view a deactivated employee's history
    (``scoped_users``, used for lists such as the daily board, shows active users only)."""
    return viewer.pk == target.pk or is_hr_plus(viewer) or _is_manager_of(viewer, target)


def can_correct(viewer, target) -> bool:
    """Like ``can_view``, deliberately ignores ``is_active`` so history of deactivated users stays correctable."""
    return is_hr_plus(viewer) or _is_manager_of(viewer, target)


class IsHRPlus(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and is_hr_plus(request.user))


class IsManagerPlus(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated
                    and (is_hr_plus(user) or user.role == UserTypes.MANAGER))


class _ReadByRoleWriteHR(BasePermission):
    """Safe methods need ``read_permission``; everything else needs HR+."""
    read_permission = IsHRPlus

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return self.read_permission().has_permission(request, view)
        return IsHRPlus().has_permission(request, view)


class ManagerReadHRWrite(_ReadByRoleWriteHR):
    read_permission = IsManagerPlus


class AuthenticatedReadHRWrite(_ReadByRoleWriteHR):
    read_permission = IsAuthenticated
