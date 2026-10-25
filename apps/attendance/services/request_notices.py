from apps.notifications.services import notify
from apps.notifications.types import NotificationKinds
from apps.users.models import User
from apps.users.types import UserTypes

APPROVALS_LINK = "/attendance/approvals?request={}"
REQUESTS_LINK = "/attendance/requests?request={}"


def _send(recipients, actor, message: str, link: str) -> None:
    users = {u.pk: u for u in recipients if actor is None or u.pk != actor.pk}
    if users:
        notify(list(users.values()), message, kind=NotificationKinds.REQUEST, title="Request",
               link=link, sender=actor)


def _label(req) -> str:
    return f"{req.get_kind_display().lower()} request"


def _range(req) -> str:
    return f"{req.start_date} → {req.end_date}" if req.end_date != req.start_date else f"{req.start_date}"


def approvers_for(req):
    """Active department managers of the requester; HR when none or the requester is a manager."""
    active = User.objects.filter(is_active=True)
    managers = []
    if req.user.role != UserTypes.MANAGER and req.user.department_id is not None:
        managers = list(active.filter(role=UserTypes.MANAGER, department_id=req.user.department_id)
                        .exclude(pk=req.user_id))
    return managers or list(active.filter(role=UserTypes.HR))


def notify_submitted(req, actor) -> None:
    name = req.user.get_full_name() or req.user.username
    _send(approvers_for(req), actor, f"New {_label(req)} from {name} ({_range(req)})",
          APPROVALS_LINK.format(req.uuid))
    if req.user_id != actor.pk:
        _send([req.user], actor, f"A {_label(req)} was filed for you by "
              f"{actor.get_full_name() or actor.username} ({_range(req)})",
              REQUESTS_LINK.format(req.uuid))


def notify_decision(req, actor, verb: str) -> None:
    recipients = [req.user] + ([req.created_by] if req.created_by_id else [])
    _send(recipients, actor, f"Your {_label(req)} ({_range(req)}) was {verb}",
          REQUESTS_LINK.format(req.uuid))
