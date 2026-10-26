import json
from functools import lru_cache

from django.apps import apps
from django.db.models import Q

from apps.commission.models import UserCommissionDetails
from apps.users.serializers.admin import user_name
from apps.users.models import BaseModel, Profile, UpdateHistory, is_redacted_field, snapshot_values

@lru_cache(maxsize=None)
def _model(name):
    return next((m for m in apps.get_models() if m.__name__ == name and issubclass(m, BaseModel)), None)


def _current(row):
    model = _model(row.model_name)
    obj = model.objects.filter(uuid=row.model_uuid).first() if model else None
    return snapshot_values(obj) if obj is not None else None


def diff_entries(rows) -> list:
    """History entries for ``rows``: each row's old snapshot diffed against the next newer snapshot
    of the same object, or against the current row for the newest."""
    entries = []
    for row in rows:  # at most one page of rows, so the per-row queries below stay small
        old = json.loads(row.previous_values)
        newer = (UpdateHistory.objects.filter(model_name=row.model_name, model_uuid=row.model_uuid, pk__gt=row.pk)
                 .order_by("pk").first())
        new = json.loads(newer.previous_values) if newer is not None else _current(row)
        changes = [] if new is None else [
            {"field": f, "old": old.get(f), "new": new.get(f)}
            for f in old if f in new and old[f] != new[f] and not is_redacted_field(f)]
        entries.append({
            "id": row.pk, "at": row.updated_at,
            "by": {"uuid": str(row.user.uuid), "name": user_name(row.user)} if row.user else None,
            "model": row.model_name, "object": str(row.model_uuid), "changes": changes})
    return entries


def user_history(user):
    """Newest-first UpdateHistory rows for the user, their profile and their commission details."""
    targets = {("User", user.uuid)}
    profile = Profile.objects.filter(user=user).first()
    if profile is not None:
        targets.add(("Profile", profile.uuid))
    details = UserCommissionDetails.objects.filter(user=user).first()
    if details is not None:
        targets.add(("UserCommissionDetails", details.uuid))
    cond = Q()
    for name, uuid in targets:
        cond |= Q(model_name=name, model_uuid=uuid)
    return UpdateHistory.objects.filter(cond).select_related("user").order_by("-pk")


def user_actions(user):
    """Newest-first UpdateHistory rows made by ``user``."""
    return UpdateHistory.objects.filter(user=user).select_related("user").order_by("-pk")
