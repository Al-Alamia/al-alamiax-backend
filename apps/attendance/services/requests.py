from datetime import date, datetime, timedelta

from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.attendance.models import Punch, Request
from apps.attendance.permissions import can_decide, can_file_for, is_hr_plus
from apps.attendance.types import PunchSource, RequestKind, RequestStatus

from . import leave, request_notices as notices
from .evaluate import recalculate

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
ATTACHMENT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
ATTACHMENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
EXCUSES = (RequestKind.LATE_EXCUSE, RequestKind.EARLY_EXCUSE)
FIELDS = ("start_date", "end_date", "leave_type", "minutes", "punch_time", "details", "cancels")


class RequestError(Exception):
    def __init__(self, message: str, type: str = "validation"):
        super().__init__(message)
        self.message = message
        self.type = type


def _now() -> datetime:
    return datetime.now()


def _today() -> date:
    return _now().date()


# ---------------------------------------------------------------- validation

def _check_attachment(attachment) -> None:
    ext = attachment.name.rsplit(".", 1)[-1].lower() if "." in attachment.name else ""
    ctype = getattr(attachment, "content_type", None)
    if ext not in ATTACHMENT_EXTENSIONS or (ctype and ctype not in ATTACHMENT_TYPES):
        raise RequestError("Attachment must be a PDF, JPEG or PNG file.")
    if attachment.size > MAX_ATTACHMENT_BYTES:
        raise RequestError("Attachment must be 5 MB or smaller.")


def _reject_foreign_fields(kind: str, v: dict) -> None:
    allowed = {
        RequestKind.LEAVE: {"leave_type"},
        RequestKind.LATE_EXCUSE: {"minutes"},
        RequestKind.EARLY_EXCUSE: {"minutes"},
        RequestKind.MISSED_PUNCH: {"punch_time"},
        RequestKind.GENERAL: set(),
        RequestKind.CANCELLATION: {"cancels"},
    }[kind]
    for name in ("leave_type", "minutes", "punch_time", "cancels"):
        if name not in allowed and v.get(name) is not None:
            raise RequestError(f"'{name}' does not apply to {kind} requests.")


def _validate_cancellation(actor, user, v: dict, existing) -> None:
    original = v.get("cancels")
    if original is None:
        raise RequestError("'cancels' is required for cancellation requests.")
    if original.user_id != user.pk or actor.pk != user.pk:
        raise PermissionDenied("Only the requester can request a cancellation.")
    if (original.status != RequestStatus.APPROVED or original.start_date > _today()
            or original.kind in (RequestKind.CANCELLATION, RequestKind.GENERAL)):
        raise RequestError("This request cannot be cancelled through a cancellation request.",
                           "invalid_state")
    dup = Request.objects.filter(cancels=original, status=RequestStatus.PENDING)
    if existing is not None:
        dup = dup.exclude(pk=existing.pk)
    if dup.exists():
        raise RequestError("A cancellation request is already pending for this request.", "overlap")
    v["start_date"], v["end_date"] = original.start_date, original.end_date


def _validate(actor, data: dict, attachment=None, existing=None) -> dict:
    """Return the cleaned field values for ``submit`` / ``edit``; raise ``RequestError``."""
    if existing is not None:
        user, kind = existing.user, existing.kind
        v = {f: getattr(existing, f) for f in FIELDS}
    else:
        user = data.get("user") or actor
        kind = data.get("kind")
        v = {f: None for f in FIELDS}
        v["details"] = ""
        if kind not in RequestKind.values:
            raise RequestError("Invalid request kind.")
        if not can_file_for(actor, user):
            raise PermissionDenied("You cannot file requests for this user.")
    v.update({f: data[f] for f in FIELDS if f in data})
    v["details"] = (v["details"] or "").strip()
    _reject_foreign_fields(kind, v)

    if kind == RequestKind.CANCELLATION:
        _validate_cancellation(actor, user, v, existing)
    elif v["start_date"] is None:
        raise RequestError("'start_date' is required.")
    start = v["start_date"]
    v["end_date"] = v["end_date"] or start
    end = v["end_date"]
    if end < start:
        raise RequestError("'end_date' must not be before 'start_date'.")
    if kind not in (RequestKind.LEAVE, RequestKind.CANCELLATION) and end != start:
        raise RequestError("Only leave requests may span more than one day.")
    if len(v["details"]) > 500:
        raise RequestError("Details must be 500 characters or fewer.")
    if kind == RequestKind.GENERAL and not v["details"]:
        raise RequestError("'details' is required for general requests.")
    if kind in EXCUSES and not (v["minutes"] and v["minutes"] > 0):
        raise RequestError("'minutes' must be greater than 0.")
    if kind == RequestKind.MISSED_PUNCH:
        if v["punch_time"] is None:
            raise RequestError("'punch_time' is required for missed punch requests.")
        if v["punch_time"] > _now():
            raise RequestError("'punch_time' must not be in the future.")
        if v["punch_time"].date() != start:
            raise RequestError("'punch_time' must be on 'start_date'.")
    if attachment is not None:
        _check_attachment(attachment)
    if kind == RequestKind.LEAVE:
        _validate_leave(user, v, has_file=attachment is not None or bool(existing and existing.attachment),
                        existing=existing)
    if kind != RequestKind.CANCELLATION:
        _check_overlap(user, kind, start, end, existing)
    return v


def _validate_leave(user, v: dict, has_file: bool, existing) -> None:
    start, end, lt = v["start_date"], v["end_date"], v["leave_type"]
    if start.year != end.year:
        raise RequestError("Leave cannot cross 1 January; file one request per year.", "crosses_year")
    if lt is None:
        raise RequestError("'leave_type' is required for leave requests.")
    if not lt.is_active:
        raise RequestError("This leave type is not active.")
    if lt.requires_attachment and not has_file:
        raise RequestError("This leave type requires an attachment.", "attachment_required")
    days = len(leave.working_dates(user, start, end))
    if days == 0:
        raise RequestError("The range contains no working days.", "no_working_days")
    if lt.uses_balance and days > leave.remaining(user, lt, start.year, exclude=existing):
        raise RequestError("Not enough leave balance.", "insufficient_balance")


def _check_overlap(user, kind, start, end, existing) -> None:
    qs = Request.objects.filter(user=user, kind=kind, start_date__lte=end, end_date__gte=start,
                                status__in=[RequestStatus.PENDING, RequestStatus.APPROVED])
    if existing is not None:
        qs = qs.exclude(pk=existing.pk)
    if qs.exists():
        raise RequestError("This overlaps an existing request of the same kind.", "overlap")


# ---------------------------------------------------------------- helpers

def _lock(req) -> Request:
    return Request.objects.select_for_update().select_related("user", "created_by").get(pk=req.pk)


def _require_state(req, *statuses) -> None:
    if req.status not in statuses:
        raise RequestError(f"A {req.status.lower()} request cannot be changed this way.",
                           "invalid_state")


def _is_owner(actor, req) -> bool:
    return actor.pk in (req.user_id, req.created_by_id)


def _recalc(req) -> None:
    pad = timedelta(days=1) if req.kind == RequestKind.MISSED_PUNCH else timedelta(0)
    recalculate(req.start_date - pad, req.end_date + pad, [req.user], _now())


def _drop_punch(req) -> None:
    if req.kind == RequestKind.MISSED_PUNCH and req.punch_id:
        Punch.objects.filter(pk=req.punch_id).delete()
        req.punch = None
        req.save(update_fields=["punch", "updated_at"])


def _decide(req, actor, status: str, note: str) -> None:
    req.status, req.decided_by, req.decided_at = status, actor, _now()
    req.decision_note = (note or "").strip()[:500]


# ---------------------------------------------------------------- lifecycle

@transaction.atomic
def submit(actor, data: dict, attachment=None) -> Request:
    v = _validate(actor, data, attachment)
    user = data.get("user") or actor
    req = Request.objects.create(user=user, created_by=actor, kind=data["kind"], attachment=attachment, **v)
    notices.notify_submitted(req, actor)
    return req


@transaction.atomic
def edit(actor, req, data: dict, attachment=None) -> Request:
    req = _lock(req)
    if not _is_owner(actor, req):
        raise PermissionDenied("Only the requester can edit this request.")
    _require_state(req, RequestStatus.PENDING)
    v = _validate(actor, data, attachment, existing=req)
    for name, value in v.items():
        setattr(req, name, value)
    if attachment is not None:
        req.attachment = attachment
    req.save()
    return req


@transaction.atomic
def approve(actor, req, note: str = "", over_balance: bool = False) -> Request:
    req = _lock(req)
    if not can_decide(actor, req):
        raise PermissionDenied("You cannot decide this request.")
    if over_balance and not is_hr_plus(actor):
        raise PermissionDenied("Only HR can approve over the balance.")
    _require_state(req, RequestStatus.PENDING)
    original = None
    if req.kind == RequestKind.LEAVE and req.leave_type.uses_balance:
        days = len(leave.working_dates(req.user, req.start_date, req.end_date))
        if days > leave.remaining(req.user, req.leave_type, req.start_date.year, exclude=req):
            if not over_balance:
                raise RequestError("Not enough leave balance.", "insufficient_balance")
            req.over_balance = True
    if req.kind == RequestKind.CANCELLATION:
        original = _lock(req.cancels)
        _require_state(original, RequestStatus.APPROVED)
    _decide(req, actor, RequestStatus.APPROVED, note)
    if req.kind == RequestKind.MISSED_PUNCH:
        req.punch = Punch.objects.create(user=req.user, timestamp=req.punch_time,
                                         source=PunchSource.REQUEST, created_by=actor,
                                         note=req.details[:255])
    req.save()
    if original is not None:
        original.status = RequestStatus.CANCELLED
        original.save(update_fields=["status", "updated_at"])
        _drop_punch(original)
        _recalc(original)
    elif req.kind in (RequestKind.LEAVE, RequestKind.LATE_EXCUSE, RequestKind.EARLY_EXCUSE,
                      RequestKind.MISSED_PUNCH):
        _recalc(req)
    req.refresh_from_db()
    notices.notify_decision(req, actor, "approved")
    return req


@transaction.atomic
def reject(actor, req, note: str = "") -> Request:
    req = _lock(req)
    if not can_decide(actor, req):
        raise PermissionDenied("You cannot decide this request.")
    _require_state(req, RequestStatus.PENDING)
    _decide(req, actor, RequestStatus.REJECTED, note)
    req.save()
    notices.notify_decision(req, actor, "rejected")
    return req


@transaction.atomic
def cancel(actor, req) -> Request:
    req = _lock(req)
    if not _is_owner(actor, req):
        raise PermissionDenied("Only the requester can cancel this request.")
    was_approved = req.status == RequestStatus.APPROVED
    if was_approved and (req.start_date <= _today() or req.kind == RequestKind.CANCELLATION):
        raise RequestError("A started request needs a cancellation request.", "invalid_state")
    _require_state(req, RequestStatus.PENDING, RequestStatus.APPROVED)
    req.status = RequestStatus.CANCELLED
    req.save(update_fields=["status", "updated_at"])
    if was_approved:
        _drop_punch(req)
        _recalc(req)
    return req


@transaction.atomic
def revoke(actor, req, note: str) -> Request:
    req = _lock(req)
    if not is_hr_plus(actor):
        raise PermissionDenied("Only HR can revoke a request.")
    if not (note or "").strip():
        raise RequestError("A note is required to revoke a request.")
    _require_state(req, RequestStatus.APPROVED)
    if req.kind == RequestKind.CANCELLATION:
        raise RequestError("A cancellation request cannot be revoked.", "invalid_state")
    _decide(req, actor, RequestStatus.REVOKED, note)
    req.save()
    _drop_punch(req)
    _recalc(req)
    notices.notify_decision(req, actor, "revoked")
    return req
