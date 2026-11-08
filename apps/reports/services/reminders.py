from datetime import datetime

from apps.notifications.services import notify
from apps.notifications.types import NotificationKinds
from apps.teams.models import Team
from apps.users.models import User
from apps.users.types import UserTypes

from ..models import ReportSubmission, ReportType
from .audience import not_working_ids, required_users
from .periods import period_for


def _name(user) -> str:
    return user.get_full_name() or user.username


def _supervisors(user) -> set:
    ids = set(Team.objects.filter(is_active=True, agents=user, leader__isnull=False)
              .values_list("leader_id", flat=True))
    if user.department_id:
        ids |= set(User.objects.filter(
            is_active=True, role=UserTypes.MANAGER, department_id=user.department_id,
        ).values_list("pk", flat=True))
    ids.discard(user.pk)
    return ids


def _missing(report_type, start, end, today) -> list:
    users = list(required_users(report_type).order_by("first_name", "username"))
    submitted = set(ReportSubmission.objects.filter(
        report_type=report_type, period_start=start).values_list("user_id", flat=True))
    off = not_working_ids([u.pk for u in users], start, end, today)
    return [u for u in users if u.pk not in submitted and u.pk not in off]


def run_reminders(now: datetime) -> int:
    """Send due reminders/digests for every active type; returns notifications sent."""
    today = now.date()
    sent = 0
    types = ReportType.objects.filter(is_active=True).exclude(last_reminded_on=today)
    for rt in types:
        if not (rt.remind_agents or rt.digest_leaders) or now.time() < rt.remind_at:
            continue
        start, end = period_for(rt, today)
        if end != today:  # weekly/monthly fire on the period's last day only
            continue
        label = start.isoformat() if start == end else f"{start.isoformat()} to {end.isoformat()}"
        missing = _missing(rt, start, end, today)
        if rt.remind_agents:
            for user in missing:
                notify([user], f"Please submit your '{rt.name}' report for {label}",
                       kind=NotificationKinds.REPORT, title="Report reminder", link="/reports")
                sent += 1
        if rt.digest_leaders:
            by_sup: dict = {}
            for user in missing:
                for sid in _supervisors(user):
                    by_sup.setdefault(sid, []).append(user)
            for sid, users in by_sup.items():
                names = ", ".join(_name(u) for u in users)
                notify([sid], f"Missing '{rt.name}' reports for {label}: {names}",
                       kind=NotificationKinds.REPORT, title="Missing reports",
                       link=f"/reports/board?type={rt.uuid}")
                sent += 1
        rt.last_reminded_on = today
        rt.save(update_fields=["last_reminded_on"])
    return sent
