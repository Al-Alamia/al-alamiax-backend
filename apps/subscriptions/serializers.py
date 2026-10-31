"""Read-only JSON builders; request bodies go straight to the services."""
from decimal import Decimal

from apps.attendance.services.locks import is_date_closed

from . import permissions as perms

ZERO = Decimal("0.00")


def user_ref(user):
    if user is None:
        return None
    return {"uuid": str(user.pk), "name": user.get_full_name() or user.username}


def money(value) -> str:
    return str(Decimal(value).quantize(ZERO))


def payment_data(user, payment) -> dict:
    return {
        "uuid": str(payment.pk),
        "amount": money(payment.amount),
        "paid_on": payment.paid_on.isoformat(),
        "method": payment.method,
        "transaction_id": payment.transaction_id,
        "note": payment.note,
        "recorded_by": user_ref(payment.recorded_by),
        "created_at": payment.created_at.isoformat(),
        "locked": is_date_closed(payment.paid_on),
        "can": perms.payment_can(user, payment),
    }


def subscription_data(user, sub, with_payments=True) -> dict:
    payments = list(sub.payments.all())
    paid = sum((p.amount for p in payments), ZERO)
    data = {
        "uuid": str(sub.pk),
        "lead": {"uuid": str(sub.lead.pk), "name": sub.lead.name, "phone": sub.lead.phone},
        "kind": sub.kind,
        "plan_name": sub.plan_name,
        "market": sub.market,
        "currency": sub.currency,
        "total_amount": money(sub.total_amount),
        "paid_amount": money(paid),
        "remaining_amount": money(sub.total_amount - paid),
        "status": sub.status(),
        "start_date": sub.start_date.isoformat(),
        "end_date": sub.end_date.isoformat(),
        "seller": user_ref(sub.seller),
        "created_by": user_ref(sub.created_by),
        "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None,
        "cancel_reason": sub.cancel_reason,
        "created_at": sub.created_at.isoformat(),
        "can": perms.row_can(user, sub),
    }
    if with_payments:
        data["payments"] = [payment_data(user, p) for p in payments]
    return data
