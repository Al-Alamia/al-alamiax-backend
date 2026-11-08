from apps.attendance.permissions import is_hr_plus
from apps.teams.permissions import is_leader
from apps.users.types import UserTypes


def can_manage_reports(user) -> bool:
    return is_hr_plus(user)


def can_view_board(user) -> bool:
    return bool(can_manage_reports(user) or user.role == UserTypes.MANAGER or is_leader(user))
