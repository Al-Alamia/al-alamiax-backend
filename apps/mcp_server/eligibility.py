from apps.users.types import UserTypes

ELIGIBLE_ROLES = {UserTypes.MANAGER, UserTypes.HR, UserTypes.OWNER}


def is_eligible(user) -> bool:
    """Active superusers and MANAGER / HR / OWNER users may connect AI apps (not while a password change is pending)."""
    if user is None or not user.is_active:
        return False
    if getattr(user, "must_change_password", False):
        return False
    return bool(user.is_superuser or user.role in ELIGIBLE_ROLES)
