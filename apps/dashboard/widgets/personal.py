from decimal import Decimal
from typing import Optional

from django.db.models import Sum

from apps.attendance.models import AttendanceDay
from apps.attendance.types import DayStatus
from apps.attendance.models import Request
from apps.attendance.types import RequestStatus
from apps.notifications.queries import active_rows
from apps.reports.models import ReportSubmission
from apps.reports.services.audience import assigned_types, is_required
from apps.reports.services.periods import recent_periods
from apps.reports.services.submissions import can_edit
from apps.salaries.models import Salary
from apps.salaries.serializers import history_row
from apps.salaries.types import SalaryStatus
from apps.treasury.models import Advance, AdvanceInstallment
from apps.treasury.types import AdvanceStatus

from . import money

CAP = 5
_WORKING = (DayStatus.PRESENT, DayStatus.LATE, DayStatus.ABSENT, DayStatus.INCOMPLETE)


def build_attendance_period(ctx) -> Optional[dict]:
    last = min(ctx.today, ctx.period_end)
    counts = {}
    for status in (AttendanceDay.objects
                   .filter(user=ctx.viewer, date__range=(ctx.period_start, last))
                   .values_list("status", flat=True)):
        counts[status] = counts.get(status, 0) + 1
    n = lambda *ss: sum(counts.get(s, 0) for s in ss)  # noqa: E731
    working = n(*_WORKING)
    late = n(DayStatus.LATE)
    return {
        "late_percent": round(100 * late / working, 1) if working else 0,
        "working_days": working,
        "present": n(DayStatus.PRESENT, DayStatus.INCOMPLETE),
        "late": late,
        "absent": n(DayStatus.ABSENT),
        "leave": n(DayStatus.LEAVE),
        "link": "ATTENDANCE",
    }


def build_my_requests(ctx) -> Optional[dict]:
    qs = Request.objects.filter(user=ctx.viewer)
    return {
        "pending_count": qs.filter(status=RequestStatus.PENDING).count(),
        "latest": [{"uuid": str(r.uuid), "kind": r.kind, "status": r.status,
                    "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat()}
                   for r in qs.order_by("-created_at")[:CAP]],
        "link": "ATTENDANCE_REQUESTS",
    }


def build_notifications(ctx) -> Optional[dict]:
    rows = active_rows(ctx.viewer, ctx.now)
    return {
        "unread_count": rows.filter(read_at__isnull=True).count(),
        "latest": [{"uuid": str(r.notification.pk), "title": r.notification.title,
                    "message": r.notification.message, "link": r.notification.link,
                    "created_at": r.notification.created_at.isoformat(),
                    "read": r.read_at is not None}
                   for r in rows[:CAP]],
        "link": "NOTIFICATIONS",
    }


def build_my_salary(ctx) -> Optional[dict]:
    salary = (Salary.objects.filter(user=ctx.viewer, status=SalaryStatus.GIVEN)
              .order_by("-period").first())
    if salary is None:
        return None
    return {**history_row(salary), "link": "MY_SALARY"}


def build_my_reports(ctx) -> Optional[dict]:
    types = assigned_types(ctx.viewer)
    if not types:
        return None
    due = []
    for rt in types:
        submitted = set(ReportSubmission.objects.filter(report_type=rt, user=ctx.viewer)
                        .values_list("period_start", flat=True))
        for start, end in recent_periods(rt, ctx.today, 7):
            if start in submitted or not is_required(rt, ctx.viewer, start, end, ctx.today):
                continue
            if can_edit(rt, ctx.viewer, start, end, ctx.today)[0]:
                due.append({"type_uuid": str(rt.uuid), "name": rt.name,
                            "period_start": start.isoformat(), "period_end": end.isoformat()})
    return {"due": due[:CAP], "due_count": len(due), "link": "REPORTS"}


def build_my_advances(ctx) -> Optional[dict]:
    advances = Advance.objects.filter(user=ctx.viewer)
    if not advances.exists():
        return None
    pending = advances.filter(status=AdvanceStatus.PENDING).first()
    outstanding = (AdvanceInstallment.objects
                   .filter(advance__user=ctx.viewer, advance__status=AdvanceStatus.APPROVED,
                           period__gte=ctx.period_key)
                   .aggregate(t=Sum("amount"))["t"] or Decimal("0"))
    return {
        "pending": None if pending is None else {
            "uuid": str(pending.uuid), "amount": money(pending.amount),
            "installments": pending.installments, "start_period": pending.start_period},
        "outstanding": money(outstanding),
        "link": "ADVANCES",
    }
