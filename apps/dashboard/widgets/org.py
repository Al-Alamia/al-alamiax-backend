from datetime import date, timedelta
from typing import Optional

from django.db.models import Count
from rest_framework.exceptions import PermissionDenied

from apps.attendance.models import AttendanceSettings, PeriodClose
from apps.attendance.permissions import is_hr_plus
from apps.attendance.services.periods import period_key_for
from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.services import included_users, period_bounds
from apps.monthly_basic.types import BasicStatus
from apps.teams.permissions import is_top
from apps.treasury.models import Advance
from apps.treasury.services import ledger
from apps.treasury.types import AdvanceStatus
from apps.users.lead_permissions import scope_queryset
from apps.users.models import Lead
from apps.users.types import LeadStatuses

from . import money


def build_payroll_period(ctx) -> Optional[dict]:
    if not is_hr_plus(ctx.viewer):
        return None
    start_day = AttendanceSettings.get().period_start_day
    prev_key = period_key_for(ctx.period_start - timedelta(days=1), start_day)
    prev_start, prev_end = period_bounds(prev_key)
    user_ids = list(included_users(prev_key).values_list("pk", flat=True))
    given = MonthlyBasic.objects.filter(period=prev_key, user_id__in=user_ids,
                                        status=BasicStatus.GIVEN).count()
    return {
        "current": {"key": ctx.period_key, "start": ctx.period_start.isoformat(),
                    "end": ctx.period_end.isoformat()},
        "previous": {"key": prev_key, "start": prev_start.isoformat(), "end": prev_end.isoformat(),
                     "closed": PeriodClose.objects.filter(period=prev_key).exists(),
                     "basics_given": given, "basics_total": len(user_ids)},
        "link": "BASIC_LIST",
    }


def build_leads(ctx) -> Optional[dict]:
    try:
        qs = scope_queryset(ctx.viewer, Lead.objects.all())
    except PermissionDenied:
        return None
    by_status = {s.value: 0 for s in LeadStatuses}
    # distinct() + default ordering would collapse rows in values_list, so aggregate instead.
    for row in qs.order_by().values("status").annotate(n=Count("pk", distinct=True)):
        by_status[row["status"]] = row["n"]
    return {
        "new_today": qs.filter(status=LeadStatuses.NEW, date__date=ctx.today).distinct().count(),
        "unassigned": by_status[LeadStatuses.NEW],
        "by_status": by_status,
        "link": "LEADS",
    }


def build_treasury(ctx) -> Optional[dict]:
    if not is_top(ctx.viewer):
        return None
    balance = ledger.balance(None)
    month = ledger.balance(date(ctx.today.year, ctx.today.month, 1))
    return {
        "balance": {k: money(v) for k, v in balance.items()},
        "month_net": money(month["net"]),
        "pending_advances": Advance.objects.filter(status=AdvanceStatus.PENDING).count(),
        "link": "TREASURY",
    }
