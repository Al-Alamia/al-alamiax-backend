from typing import Optional

from django.db.models import Q

from apps.attendance.permissions import is_hr_plus, scoped_users
from apps.teams.permissions import is_top, supervised_users
from apps.users.models import User

from .models import ActivityEvent, Area


def can_view_activity(viewer) -> bool:
    if is_hr_plus(viewer):
        return True
    return supervised_users(viewer).exclude(pk=viewer.pk).exists()


def scope_user_ids(viewer) -> Optional[set]:
    """None means everyone (HR+, including inactive users)."""
    if is_hr_plus(viewer):
        return None
    return set(supervised_users(viewer).exclude(pk=viewer.pk).values_list("pk", flat=True))


def scope_users(viewer):
    if is_hr_plus(viewer):
        return User.objects.filter(is_active=True).exclude(pk=viewer.pk)
    return supervised_users(viewer).exclude(pk=viewer.pk)


def visible_events(viewer):
    qs = ActivityEvent.objects.select_related("actor", "subject")
    ids = scope_user_ids(viewer)
    if ids is not None:
        qs = qs.filter(
            Q(subject_id__in=ids)
            | Q(subject__isnull=True, actor_id__in=ids)
            | Q(actor=viewer)
        )
    if not is_top(viewer):
        qs = qs.exclude(area=Area.TREASURY)
    if not is_hr_plus(viewer):
        qs = qs.exclude(area=Area.PAYROLL)
        # penalties, advances and HR files are for the subject's department manager only
        # (not team leaders); the actor always sees their own.
        managed = scoped_users(viewer).exclude(pk=viewer.pk).values_list("pk", flat=True)
        sensitive = (Q(verb__startswith="penalty.") | Q(verb__startswith="advance.")
                     | Q(verb__startswith="file."))
        qs = qs.filter(~sensitive | Q(actor=viewer) | Q(subject_id__in=list(managed)))
    return qs
