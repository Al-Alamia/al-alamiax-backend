from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.attendance.services.locks import closed_period_for

from ..errors import ReportError
from ..models import ReportField, ReportSubmission, ReportValue
from ..types import FieldKind
from .audience import is_required
from .periods import period_for

MAX_NUMBER = Decimal("9999999999.99")
MAX_TEXT = 500
MAX_ACCOUNTS = 50
MAX_ACCOUNT_LEN = 100

_MESSAGES = {
    "inactive": "This report is not active.",
    "not_assigned": "This report is not assigned to you.",
    "future": "This period has not started yet.",
    "period_closed": "The payroll period is closed.",
    "window_passed": "The edit window for this period has passed.",
}


def can_edit(report_type, user, start: date, end: date, today: date) -> "tuple[bool, str | None]":
    if not report_type.is_active:
        return False, "inactive"
    existing = ReportSubmission.objects.filter(
        report_type=report_type, user=user, period_start=start).exists()
    if not existing and not is_required(report_type, user, start, end, today):
        return False, "not_assigned"
    if start > today:
        return False, "future"
    if closed_period_for(start, end) is not None:
        return False, "period_closed"
    window = report_type.edit_window_days
    if window is not None and (today - end).days > window:
        return False, "window_passed"
    return True, None


def _clean_number(raw):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str, Decimal)):
        raise ValueError("Enter a valid number.")
    try:
        d = Decimal(str(raw).strip())
    except InvalidOperation:
        raise ValueError("Enter a valid number.")
    if not d.is_finite():
        raise ValueError("Enter a valid number.")
    if d < 0:
        raise ValueError("Must not be negative.")
    if d > MAX_NUMBER:
        raise ValueError("Number is too large.")
    return d.quantize(Decimal("0.01"))


def _clean_text(raw):
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("Enter text.")
    if len(raw) > MAX_TEXT:
        raise ValueError(f"At most {MAX_TEXT} characters.")
    return raw


def _clean_accounts(raw):
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)) or not all(isinstance(x, str) for x in raw):
        raise ValueError("Enter a list of accounts.")
    items = [x.strip() for x in raw]
    items = [x for x in items if x]
    if len(items) > MAX_ACCOUNTS:
        raise ValueError(f"At most {MAX_ACCOUNTS} accounts.")
    if any(len(x) > MAX_ACCOUNT_LEN for x in items):
        raise ValueError(f"Each account at most {MAX_ACCOUNT_LEN} characters.")
    return items


_CLEANERS = {
    FieldKind.NUMBER: ("number", _clean_number),
    FieldKind.TEXT: ("text", _clean_text),
    FieldKind.ACCOUNTS: ("accounts", _clean_accounts),
}


def _is_empty(kind, cleaned) -> bool:
    if kind == FieldKind.NUMBER:
        return cleaned is None
    if kind == FieldKind.TEXT:
        return not cleaned.strip()
    return not cleaned


def _validate(report_type, values: dict) -> dict:
    """Return {ReportField: cleaned value}; raise ReportError(invalid) keyed by field uuid."""
    fields = {str(f.uuid): f for f in ReportField.objects.filter(
        section__report_type=report_type).select_related("section")}
    errors: dict = {}
    cleaned: dict = {}
    for key, raw in (values or {}).items():
        key = str(key)
        field = fields.get(key)
        if field is None:
            errors[key] = "Unknown field."
            continue
        if not field.is_active or not field.section.is_active:
            errors[key] = "This field is no longer active."
            continue
        attr, fn = _CLEANERS[field.kind]
        try:
            cleaned[field] = fn(raw)
        except ValueError as e:
            errors[key] = str(e)
    for key, field in fields.items():
        if (field.required and field.is_active and field.section.is_active
                and key not in errors
                and (field not in cleaned or _is_empty(field.kind, cleaned[field]))):
            errors[key] = "This field is required."
    if errors:
        raise ReportError("Invalid report values.", "invalid", errors)
    return cleaned


@transaction.atomic
def save_submission(report_type, user, any_date: date, values: dict, today: date) -> ReportSubmission:
    start, end = period_for(report_type, any_date)
    ok, reason = can_edit(report_type, user, start, end, today)
    if not ok:
        raise ReportError(_MESSAGES[reason], reason)
    cleaned = _validate(report_type, values)

    submission = (ReportSubmission.objects.select_for_update()
                  .filter(report_type=report_type, user=user, period_start=start).first())
    if submission is None:
        submission = ReportSubmission.objects.create(
            report_type=report_type, user=user, period_start=start, period_end=end,
            department=user.department, project=user.project,
            submitted_at=timezone.now(), is_late=today > end)
    else:
        submission.is_late = submission.is_late or today > end
        submission.submitted_at = timezone.now()
        submission.save(update_fields=["is_late", "submitted_at", "updated_at"])
        submission.values.all().delete()

    rows = []
    for field, val in cleaned.items():
        attr, _ = _CLEANERS[field.kind]
        rows.append(ReportValue(submission=submission, field=field, **{attr: val}))
    ReportValue.objects.bulk_create(rows)
    return submission


def value_payload(value: ReportValue):
    kind = value.field.kind
    if kind == FieldKind.NUMBER:
        return None if value.number is None else str(value.number)
    if kind == FieldKind.TEXT:
        return value.text
    return value.accounts


def submission_values(submission: ReportSubmission) -> dict:
    return {str(v.field_id): value_payload(v)
            for v in submission.values.select_related("field")}
