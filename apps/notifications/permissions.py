from apps.users.types import UserTypes


def can_send(user) -> bool:
    return bool(user.is_superuser or user.role in (UserTypes.OWNER, UserTypes.HR, UserTypes.MANAGER))


def sees_all_sent(user) -> bool:
    return bool(user.is_superuser or user.role == UserTypes.OWNER)
