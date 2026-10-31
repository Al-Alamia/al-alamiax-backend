import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Optional

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.attendance.services.locks import PeriodClosed, assert_open
from apps.users.services.leads import log_update
from apps.users.types import LeadStatuses, LeadUpdateTypes, StockMarkets

from . import permissions as perms
from .models import Payment, Subscription
from .types import Currency, PaymentMethod, SubscriptionKind

ZERO = Decimal("0.00")
_MONEY_RE = re.compile(r"^\d+(\.\d{1,2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_MONEY = Decimal(10) ** 10
_FROZEN_BY_CLOSED_PAYMENTS = ("kind", "market", "currency", "total_amount", "seller")
_MISSING = object()
DENIED = "You do not have permission to do this"


class SubscriptionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _invalid(field: str, why: str = "is invalid") -> SubscriptionError:
    return SubscriptionError("invalid", f"{field} {why}")


# ----- parsing -----

def _money(data: Mapping, field: str) -> Decimal:
    raw = data.get(field)
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        raise _invalid(field)
    text = str(raw).strip()
    if not _MONEY_RE.match(text):
        raise _invalid(field)
    value = Decimal(text)
    if value <= 0 or value >= _MAX_MONEY:
        raise _invalid(field)
    return value.quantize(ZERO)


def _date(data: Mapping, field: str) -> date:
    raw = data.get(field)
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        raise _invalid(field)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise _invalid(field)


def _choice(data: Mapping, field: str, choices) -> str:
    raw = data.get(field)
    if not isinstance(raw, str) or raw not in set(choices.values):
        raise _invalid(field)
    return raw


def _text(data: Mapping, field: str, max_len: int, required: bool, default: str = "") -> str:
    raw = data.get(field, default)
    if raw is None and not required:
        raw = ""
    if not isinstance(raw, str):
        raise _invalid(field)
    raw = raw.strip()
    if required and not raw:
        raise _invalid(field)
    if len(raw) > max_len:
        raise _invalid(field)
    return raw


def _seller(lead, raw) -> Any:
    if not isinstance(raw, str):
        raise _invalid("seller")
    try:
        user = perms.seller_choices(lead).filter(pk=raw).first()
    except (DjangoValidationError, ValueError):
        user = None
    if user is None:
        raise _invalid("seller")
    return user


def _parse_subscription(data: Mapping, current: Optional[Subscription]) -> dict:
    """Validated field values: all required on create, only the supplied ones on update (merged for date checks)."""
    out = {}
    parsers = {
        "kind": lambda: _choice(data, "kind", SubscriptionKind),
        "plan_name": lambda: _text(data, "plan_name", 100, True),
        "market": lambda: _choice(data, "market", StockMarkets),
        "currency": lambda: _choice(data, "currency", Currency),
        "total_amount": lambda: _money(data, "total_amount"),
        "start_date": lambda: _date(data, "start_date"),
        "end_date": lambda: _date(data, "end_date"),
    }
    for field, parse in parsers.items():
        if current is None or field in data:
            out[field] = parse()
    start = out.get("start_date", current.start_date if current else None)
    end = out.get("end_date", current.end_date if current else None)
    if end < start:
        raise _invalid("end_date", "must not be before start_date")
    return out


def _parse_payment(data: Mapping, current: Optional[Payment]) -> dict:
    out = {}
    parsers = {
        "amount": lambda: _money(data, "amount"),
        "paid_on": lambda: _date(data, "paid_on"),
        "method": lambda: _choice(data, "method", PaymentMethod),
        "transaction_id": lambda: _text(data, "transaction_id", 100, False),
        "note": lambda: _text(data, "note", 500, False),
    }
    optional = ("transaction_id", "note")
    for field, parse in parsers.items():
        if field in data or (current is None and field not in optional):
            out[field] = parse()
    return out


# ----- helpers -----

def paid_amount(sub) -> Decimal:
    return Payment.objects.filter(subscription=sub).aggregate(s=Sum("amount"))["s"] or ZERO


def _assert_open(*days: date) -> None:
    try:
        for d in days:
            assert_open(d)
    except PeriodClosed as exc:
        raise SubscriptionError("period_closed", str(exc))


def _lock(sub) -> Subscription:
    return Subscription.objects.select_for_update().get(pk=sub.pk)


def _can_add_payment(actor, sub) -> bool:
    return perms.lead_can(actor, sub.lead)["create"] or sub.seller_id == actor.pk


def _payment_log(prefix: str, sub, amount, paid_on) -> str:
    return f"{prefix}: {amount} {sub.currency} on {paid_on}"


# ----- subscriptions -----

def create_subscription(actor, lead, data: Mapping) -> Subscription:
    caps = perms.lead_can(actor, lead)
    if not caps["create"]:
        raise PermissionDenied(DENIED)
    fields = _parse_subscription(data, None)
    if caps["choose_seller"]:
        if "seller" not in data:
            raise _invalid("seller", "is required")
        seller = _seller(lead, data.get("seller"))
    else:
        seller = actor
    with transaction.atomic():
        sub = Subscription.objects.create(lead=lead, seller=seller, created_by=actor, **fields)
        if lead.status != LeadStatuses.SUBSCRIBER:
            old = lead.status
            lead.status = LeadStatuses.SUBSCRIBER
            lead.save()
            log_update(lead, actor, LeadUpdateTypes.STATUS, from_value=old, to_value=LeadStatuses.SUBSCRIBER)
        log_update(lead, actor, LeadUpdateTypes.SUBSCRIPTION,
                   to_value=f"created: {sub.plan_name} {sub.total_amount} {sub.currency}")
    return sub


def update_subscription(actor, sub, data: Mapping) -> Subscription:
    if not perms.can_manage(actor, sub):
        raise PermissionDenied(DENIED)
    with transaction.atomic():
        locked = _lock(sub)
        if locked.cancelled_at:
            raise SubscriptionError("cancelled", "Subscription is cancelled")
        fields = _parse_subscription(data, locked)
        if "seller" in data and str(data.get("seller")) != str(locked.seller_id):
            fields["seller"] = _seller(locked.lead, data.get("seller"))
        changed = {f for f, v in fields.items() if getattr(locked, f if f != "seller" else "seller_id") != (v.pk if f == "seller" else v)}
        paid = paid_amount(locked)
        if changed & set(_FROZEN_BY_CLOSED_PAYMENTS):
            closed = [p.paid_on for p in locked.payments.all()]
            _assert_open(*closed)
        if "total_amount" in changed and fields["total_amount"] < paid:
            raise SubscriptionError("overpaid", "Total amount cannot be below the amount already paid")
        for f in changed:
            setattr(locked, f, fields[f])
        locked.save()
        log_update(locked.lead, actor, LeadUpdateTypes.SUBSCRIPTION, to_value="updated")
    return locked


def cancel_subscription(actor, sub, reason) -> Subscription:
    if not perms.can_manage(actor, sub):
        raise PermissionDenied(DENIED)
    reason = _text({"reason": reason}, "reason", 300, True)
    with transaction.atomic():
        locked = _lock(sub)
        if locked.cancelled_at:
            raise SubscriptionError("cancelled", "Subscription is already cancelled")
        locked.cancelled_at = timezone.now()
        locked.cancelled_by = actor
        locked.cancel_reason = reason
        locked.save()
        log_update(locked.lead, actor, LeadUpdateTypes.SUBSCRIPTION, to_value="cancelled", note=reason)
    return locked


def delete_subscription(actor, sub) -> None:
    if not perms.can_manage(actor, sub):
        raise PermissionDenied(DENIED)
    with transaction.atomic():
        locked = _lock(sub)
        if locked.payments.exists():
            raise SubscriptionError("has_payments", "Subscription has payments and cannot be deleted")
        lead, plan = locked.lead, locked.plan_name
        locked.delete()
        log_update(lead, actor, LeadUpdateTypes.SUBSCRIPTION, to_value=f"deleted: {plan}")


# ----- payments -----

def _validate_payment(locked: Subscription, amount: Decimal, paid_on: date, exclude_pk=None) -> None:
    if paid_on > date.today():
        raise SubscriptionError("future_date", "Payment date cannot be in the future")
    _assert_open(paid_on)
    others = Payment.objects.filter(subscription=locked)
    if exclude_pk is not None:
        others = others.exclude(pk=exclude_pk)
    paid = others.aggregate(s=Sum("amount"))["s"] or ZERO
    if paid + amount > locked.total_amount:
        raise SubscriptionError("overpaid", "Payments would exceed the subscription total")


def add_payment(actor, sub, data: Mapping) -> Payment:
    if not _can_add_payment(actor, sub):
        raise PermissionDenied(DENIED)
    fields = _parse_payment(data, None)
    with transaction.atomic():
        locked = _lock(sub)
        if locked.cancelled_at:
            raise SubscriptionError("cancelled", "Subscription is cancelled")
        _validate_payment(locked, fields["amount"], fields["paid_on"])
        payment = Payment.objects.create(subscription=locked, recorded_by=actor, **fields)
        log_update(locked.lead, actor, LeadUpdateTypes.PAYMENT,
                   to_value=_payment_log("payment", locked, payment.amount, payment.paid_on))
    return payment


def _can_edit_payment(actor, payment) -> bool:
    return payment.recorded_by_id == actor.pk or perms.can_manage(actor, payment.subscription)


def update_payment(actor, payment, data: Mapping) -> Payment:
    if not _can_edit_payment(actor, payment):
        raise PermissionDenied(DENIED)
    fields = _parse_payment(data, payment)
    with transaction.atomic():
        locked = _lock(payment.subscription)
        current = Payment.objects.get(pk=payment.pk)
        if locked.cancelled_at:
            raise SubscriptionError("cancelled", "Subscription is cancelled")
        _assert_open(current.paid_on)
        _validate_payment(
            locked, fields.get("amount", current.amount), fields.get("paid_on", current.paid_on),
            exclude_pk=current.pk,
        )
        for f, v in fields.items():
            setattr(current, f, v)
        current.save()
        log_update(locked.lead, actor, LeadUpdateTypes.PAYMENT,
                   to_value=_payment_log("payment updated", locked, current.amount, current.paid_on))
    return current


def delete_payment(actor, payment) -> None:
    if not _can_edit_payment(actor, payment):
        raise PermissionDenied(DENIED)
    with transaction.atomic():
        locked = _lock(payment.subscription)
        current = Payment.objects.get(pk=payment.pk)
        _assert_open(current.paid_on)
        amount, paid_on = current.amount, current.paid_on
        current.delete()
        log_update(locked.lead, actor, LeadUpdateTypes.PAYMENT,
                   to_value=_payment_log("payment deleted", locked, amount, paid_on))
