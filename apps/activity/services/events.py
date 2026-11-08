import uuid
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from apps.activity.models import ActivityEvent
from apps.activity.verbs import VERBS


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _user_or_none(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return user


def record_event(actor, verb, *, subject=None, target=None, label="", data=None) -> ActivityEvent:
    """Record an activity event inside the caller's transaction."""
    try:
        area = VERBS[verb]
    except KeyError:
        raise ValueError(f"Unknown activity verb: {verb!r}")
    return ActivityEvent.objects.create(
        actor=_user_or_none(actor),
        subject=_user_or_none(subject),
        verb=verb,
        area=area,
        target_type=target._meta.model_name if target is not None else "",
        target_uuid=(target.pk if target is not None and isinstance(target.pk, uuid.UUID)
                     else None),
        target_label=(label or "")[:200],
        data=_jsonable(data or {}),
    )
