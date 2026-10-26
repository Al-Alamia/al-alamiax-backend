from datetime import date

from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated

from apps.attendance.types import RequestKind, RequestStatus
from apps.users.models import User
from apps.users.types import UserTypes


def is_hr_plus(user) -> bool:
    return bool(user.is_superuser or user.role in (UserTypes.HR, UserTypes.OWNER))


def is_manager_of(viewer, target) -> bool:
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
    return viewer.pk == target.pk or is_hr_plus(viewer) or is_manager_of(viewer, target)


def can_correct(viewer, target) -> bool:
    """Like ``can_view``, deliberately ignores ``is_active`` so history of deactivated users stays correctable."""
    if is_hr_plus(viewer):
        return True
    if viewer.pk == target.pk:  # nobody below HR approves their own corrections
        return False
    return is_manager_of(viewer, target)


def can_decide(viewer, req) -> bool:
    """Approve/reject: ``can_correct`` plus HR cannot decide their own request (only Owner/superuser)."""
    if viewer.role == UserTypes.HR and viewer.pk == req.user_id and not viewer.is_superuser:
        return False
    return can_correct(viewer, req.user)


def can_file_for(viewer, target) -> bool:
    return viewer.pk == target.pk or is_hr_plus(viewer) or is_manager_of(viewer, target)


def request_can(viewer, req, today: date) -> dict:
    """The ``can`` flags serialized with every request."""
    owner = viewer.pk in (req.user_id, req.created_by_id)
    pending = req.status == RequestStatus.PENDING
    approved = req.status == RequestStatus.APPROVED
    decide = pending and can_decide(viewer, req)
    cancellation = req.kind == RequestKind.CANCELLATION
    if decide and cancellation:  # the original must still be approved to be cancelled
        decide = req.cancels is not None and req.cancels.status == RequestStatus.APPROVED
    reject = pending and can_decide(viewer, req)
    return {
        "edit": owner and pending and not cancellation,
        "cancel": owner and (pending or (approved and req.start_date > today
                                         and req.kind != RequestKind.CANCELLATION)),
        "request_cancellation": (viewer.pk == req.user_id and approved and req.start_date <= today
                                 and req.kind not in (RequestKind.CANCELLATION, RequestKind.GENERAL)),
        "approve": decide,
        "reject": reject,
        "revoke": approved and is_hr_plus(viewer) and req.kind != RequestKind.CANCELLATION,
        "approve_over_balance": (decide and is_hr_plus(viewer) and req.kind == RequestKind.LEAVE),
    }


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
