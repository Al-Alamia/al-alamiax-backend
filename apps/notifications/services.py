from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from apps.users.models import User
from apps.users.types import UserTypes

from .models import Notification, NotificationRecipient
from .types import NotificationKinds


def _pk(obj):
    return getattr(obj, "pk", obj)


def _check_manager_scope(sender, user_ids, department_ids, project_ids, roles, everyone):
    if roles or everyone:
        raise PermissionDenied("You can only notify users in your own department or project.")
    sender_dept = str(sender.department_id) if sender.department_id else None
    sender_proj = str(sender.project_id) if sender.project_id else None
    if any(str(d) != sender_dept for d in department_ids) or any(str(p) != sender_proj for p in project_ids):
        raise PermissionDenied("You can only notify your own department or project.")
    if user_ids:
        for u in User.objects.filter(pk__in=user_ids):
            in_dept = sender.department_id is not None and u.department_id == sender.department_id
            in_proj = sender.project_id is not None and u.project_id == sender.project_id
            if not (in_dept or in_proj):
                raise PermissionDenied("You can only notify users in your own department or project.")


def resolve_audience(sender, *, users=(), departments=(), projects=(), roles=(), everyone=False):
    user_ids = [_pk(u) for u in users]
    department_ids = [_pk(d) for d in departments]
    project_ids = [_pk(p) for p in projects]
    roles = list(roles)

    unrestricted = (
        sender is None
        or sender.is_superuser
        or sender.role in (UserTypes.OWNER, UserTypes.HR)
    )
    if not unrestricted:
        _check_manager_scope(sender, user_ids, department_ids, project_ids, roles, everyone)

    qs = User.objects.filter(is_active=True)
    if not everyone:
        q = Q()
        if user_ids:
            q |= Q(pk__in=user_ids)
        if department_ids:
            q |= Q(department_id__in=department_ids)
        if project_ids:
            q |= Q(project_id__in=project_ids)
        if roles:
            q |= Q(role__in=roles)
        if not q:
            return qs.none()
        qs = qs.filter(q)
    if sender is not None:
        qs = qs.exclude(pk=sender.pk)
    return qs.distinct()


def is_safe_link(link):
    """In-app path only: empty, or starts with "/" (not "//") and has no backslash."""
    if not link:
        return True
    return isinstance(link, str) and link.startswith("/") and not link.startswith("//") and "\\" not in link


def notify(users, message, *, kind=NotificationKinds.MANUAL, title="", link="", sender=None,
           expires_at=None, audience=None):
    user_ids = list(dict.fromkeys(_pk(u) for u in users))
    if not user_ids:
        raise ValueError("users must not be empty")
    if not (message or "").strip():
        raise ValueError("message must not be blank")
    if not is_safe_link(link):
        raise ValueError("link must be an in-app path")
    with transaction.atomic():
        notification = Notification.objects.create(
            kind=kind, title=title, message=message, link=link, sender=sender,
            expires_at=expires_at, audience=audience or {},
        )
        NotificationRecipient.objects.bulk_create(
            [NotificationRecipient(notification=notification, user_id=uid) for uid in user_ids]
        )
    return notification
