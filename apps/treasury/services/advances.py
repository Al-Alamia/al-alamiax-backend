import datetime as dt
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.attendance.models import AttendanceSettings
from apps.attendance.permissions import is_hr_plus
from apps.attendance.services.locks import closed_period_for
from apps.attendance.services.periods import period_key_for
from apps.monthly_basic.permissions import can_manage_basic
from apps.notifications.services import notify
from apps.notifications.types import NotificationKinds
from apps.payroll_config.services import basic_for
from apps.users.models import User
from apps.users.types import UserTypes

from ..models import Advance, AdvanceInstallment, TreasuryEntry
from ..types import AdvanceStatus, Category, Direction
from .errors import TreasuryError
from .ledger import parse_amount, reverse_entry

_CENT = Decimal("0.01")
MAX_INSTALLMENTS = 6


def _ms():
    # Lazy: monthly_basic will import this module for the advance deduction hook.
    from apps.monthly_basic import services as ms
    return ms


def _name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def split(amount: Decimal, n: int) -> list:
    q = (amount / n).quantize(_CENT, rounding=ROUND_DOWN)
    return [q] * (n - 1) + [amount - q * (n - 1)]


def period_keys(start: str, n: int) -> list:
    y, m = int(start[:4]), int(start[5:7])
    idx = y * 12 + (m - 1)
    return [f"{(idx + i) // 12:04d}-{(idx + i) % 12 + 1:02d}" for i in range(n)]


def approvers_for(user) -> list:
    candidates = User.objects.filter(is_active=True).filter(
        Q(is_superuser=True) | Q(role__in=(UserTypes.HR, UserTypes.OWNER))
        | (Q(role=UserTypes.MANAGER, department_id=user.department_id)
           if user.department_id is not None else Q(pk__in=[]))
    ).exclude(pk=user.pk)
    return [u for u in candidates if (is_hr_plus(u) or u.role == UserTypes.MANAGER)
            and can_manage_basic(u, user)]


def can_decide(viewer, advance) -> bool:
    return viewer.pk != advance.user_id and can_manage_basic(viewer, advance.user)


def _notify(users, message, by, title):
    users = [u for u in users if u.pk != by.pk]
    if users:
        notify(users, message, kind=NotificationKinds.PAYROLL, title=title, link="/advances", sender=by)


def _validate_schedule(user, amount, n, start_period):
    ms = _ms()
    try:
        month = ms.month_of(start_period)
    except ms.BasicError:
        raise TreasuryError("invalid", "Invalid start period.")
    if start_period < period_key_for(dt.date.today(), AttendanceSettings.get().period_start_day):
        raise TreasuryError("past_period", "The start period is in the past.")
    keys = period_keys(start_period, n)
    for key in keys:
        start, end = ms.period_bounds(key)
        closed = closed_period_for(start, end)
        if closed is not None:
            raise TreasuryError("period_closed", f"Payroll period {closed} is closed.")
    basic = basic_for(user, month)
    if basic is None:
        raise TreasuryError("no_basic", "No basic salary is set for the start period.")
    if amount > basic:
        raise TreasuryError("over_limit", "The amount exceeds the basic salary.")
    return keys


def request_advance(by, user, amount, installments, start_period, reason="") -> Advance:
    if by.pk != user.pk and not can_manage_basic(by, user):
        raise TreasuryError("forbidden", "You cannot request an advance for this user.")
    amount = parse_amount(amount)
    if (isinstance(installments, bool) or not isinstance(installments, int)
            or not 1 <= installments <= MAX_INSTALLMENTS):
        raise TreasuryError("invalid", "Installments must be between 1 and 6.")
    _validate_schedule(user, amount, installments, start_period)
    reason = reason.strip() if isinstance(reason, str) else ""
    with transaction.atomic():
        if Advance.objects.select_for_update().filter(user=user, status=AdvanceStatus.PENDING).exists():
            raise TreasuryError("pending_exists", "This user already has a pending advance.")
        advance = Advance.objects.create(
            user=user, requested_by=by, amount=amount, installments=installments,
            start_period=start_period, reason=reason)
    _notify(approvers_for(user), f"{_name(user)} requested an advance of {amount}.", by, "Advance request")
    return advance


def _lock(advance) -> Advance:
    return Advance.objects.select_for_update().select_related("user").get(pk=advance.pk)


def _require_decider(by, advance):
    if not can_decide(by, advance):
        raise TreasuryError("forbidden", "You cannot decide this advance.")


def _require_pending(advance):
    if advance.status != AdvanceStatus.PENDING:
        raise TreasuryError("not_pending", "This advance is not pending.")


def approve_advance(by, advance, note="") -> Advance:
    with transaction.atomic():
        advance = _lock(advance)
        _require_pending(advance)
        _require_decider(by, advance)
        keys = _validate_schedule(advance.user, advance.amount, advance.installments, advance.start_period)
        AdvanceInstallment.objects.bulk_create([
            AdvanceInstallment(advance=advance, period=k, amount=a)
            for k, a in zip(keys, split(advance.amount, advance.installments))])
        TreasuryEntry.objects.create(
            direction=Direction.OUT, category=Category.ADVANCE, amount=advance.amount,
            date=dt.date.today(), details=f"Advance — {_name(advance.user)}"[:250],
            advance=advance, created_by=by)
        _decide(advance, by, AdvanceStatus.APPROVED, note)
    _notify([advance.user], "Your advance request was approved.", by, "Advance approved")
    return advance


def _decide(advance, by, status, note):
    advance.status = status
    advance.decided_by = by
    advance.decided_at = timezone.now()
    advance.decision_note = note.strip() if isinstance(note, str) else ""
    advance.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])


def reject_advance(by, advance, note) -> Advance:
    note = note.strip() if isinstance(note, str) else ""
    if not note:
        raise TreasuryError("invalid", "A note is required.")
    with transaction.atomic():
        advance = _lock(advance)
        _require_pending(advance)
        _require_decider(by, advance)
        _decide(advance, by, AdvanceStatus.REJECTED, note)
    _notify([advance.user], "Your advance request was rejected.", by, "Advance rejected")
    return advance


def withdraw_advance(by, advance) -> Advance:
    with transaction.atomic():
        advance = _lock(advance)
        _require_pending(advance)
        if by.pk not in (advance.requested_by_id, advance.user_id):
            raise TreasuryError("forbidden", "You cannot withdraw this advance.")
        advance.status = AdvanceStatus.WITHDRAWN
        advance.save(update_fields=["status", "updated_at"])
    return advance


def cancel_advance(by, advance, reason) -> Advance:
    reason = reason.strip() if isinstance(reason, str) else ""
    if not reason:
        raise TreasuryError("invalid", "A reason is required.")
    from apps.monthly_basic.models import MonthlyBasic
    from apps.monthly_basic.types import BasicStatus
    with transaction.atomic():
        advance = _lock(advance)
        if advance.status != AdvanceStatus.APPROVED:
            raise TreasuryError("not_approved", "This advance is not approved.")
        _require_decider(by, advance)
        periods = list(advance.schedule.values_list("period", flat=True))
        if MonthlyBasic.objects.filter(user=advance.user, period__in=periods,
                                       status=BasicStatus.GIVEN).exists():
            raise TreasuryError("deducted", "An installment was already deducted.")
        payout = TreasuryEntry.objects.select_for_update().filter(
            advance=advance, reverses__isnull=True, reversed_at__isnull=True).first()
        if payout is not None:
            reverse_entry(by, payout, reason, allow_advance=True)
        advance.schedule.all().delete()
        advance.status = AdvanceStatus.CANCELLED
        advance.cancel_reason = reason
        advance.save(update_fields=["status", "cancel_reason", "updated_at"])
    _notify([advance.user], "Your approved advance was cancelled.", by, "Advance cancelled")
    return advance


def installments_for(user_ids, period) -> dict:
    rows = (AdvanceInstallment.objects
            .filter(advance__user_id__in=list(user_ids), advance__status=AdvanceStatus.APPROVED, period=period)
            .values("advance__user_id").annotate(total=Sum("amount")))
    return {r["advance__user_id"]: r["total"] for r in rows}


def installment_rows(user, period) -> list:
    out = []
    for inst in (AdvanceInstallment.objects
                 .filter(advance__user=user, advance__status=AdvanceStatus.APPROVED, period=period)
                 .select_related("advance").order_by("advance__created_at")):
        keys = list(inst.advance.schedule.order_by("period").values_list("period", flat=True))
        out.append({"advance": inst.advance_id, "index": keys.index(period) + 1,
                    "count": len(keys), "amount": inst.amount})
    return out
