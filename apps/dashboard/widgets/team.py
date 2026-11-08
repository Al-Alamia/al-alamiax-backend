from typing import Optional

from apps.attendance.models import AttendanceDay, Request
from apps.attendance.permissions import can_decide as can_decide_request
from apps.attendance.permissions import is_hr_plus, scoped_users
from apps.attendance.types import DayStatus, RequestStatus
from apps.reports.models import ReportSubmission, ReportType
from apps.reports.permissions import can_view_board
from apps.reports.services.audience import not_working_ids, required_users
from apps.reports.services.periods import period_for
from apps.teams.permissions import supervised_users
from apps.treasury.models import Advance
from apps.treasury.services.advances import can_decide as can_decide_advance
from apps.treasury.types import AdvanceStatus
from apps.users.types import UserTypes

from . import user_ref

CAP = 5
_OTHER = (DayStatus.WEEKEND, DayStatus.HOLIDAY, DayStatus.NO_SHIFT, DayStatus.EXCUSED)
_COUNTED = (DayStatus.PRESENT, DayStatus.LATE, DayStatus.ABSENT, DayStatus.INCOMPLETE,
            DayStatus.LEAVE)


def _manages_department(viewer) -> bool:
    return viewer.role == UserTypes.MANAGER and viewer.department_id is not None


def build_team_today(ctx) -> Optional[dict]:
    viewer = ctx.viewer
    if not (is_hr_plus(viewer) or _manages_department(viewer)):
        return None
    scope_ids = list(ctx.team_scope.values_list("pk", flat=True))
    days = {d.user_id: d for d in AttendanceDay.objects
            .filter(user_id__in=scope_ids, date=ctx.today).select_related("user")}
    counts = {s.value: 0 for s in _COUNTED}
    counts.update(NONE=0, OTHER=0)
    for uid in scope_ids:
        day = days.get(uid)
        if day is None:
            counts["NONE"] += 1
        elif day.status in _COUNTED:
            counts[day.status] += 1
        else:
            counts["OTHER"] += 1
    late_days = sorted((d for d in days.values() if d.status == DayStatus.LATE),
                       key=lambda d: (-d.late_minutes, d.user.username))
    late = [{**user_ref(d.user), "late_minutes": d.late_minutes} for d in late_days[:CAP]]
    absent_days = sorted((d for d in days.values() if d.status == DayStatus.ABSENT),
                         key=lambda d: d.user.username)
    absent = [user_ref(d.user) for d in absent_days[:CAP]]
    return {"total": len(scope_ids), "counts": counts, "late": late, "absent": absent,
            "link": "ATTENDANCE"}


def build_approvals(ctx) -> Optional[dict]:
    viewer = ctx.viewer
    # Leaders cannot approve advances (approvers_for: HR+, or a MANAGER of the same department).
    allowed = is_hr_plus(viewer) or _manages_department(viewer)
    requests = sum(
        1 for r in Request.objects.filter(status=RequestStatus.PENDING,
                                          user__in=scoped_users(viewer)).select_related("user", "cancels")
        if can_decide_request(viewer, r))
    advances = sum(
        1 for a in Advance.objects.filter(status=AdvanceStatus.PENDING).select_related("user")
        if can_decide_advance(viewer, a))
    total = requests + advances
    if not allowed and total == 0:
        return None
    return {"requests": requests, "advances": advances, "total": total,
            "link": "ATTENDANCE_APPROVALS", "advances_link": "ADVANCES"}


def build_team_reports(ctx) -> Optional[dict]:
    viewer = ctx.viewer
    if not can_view_board(viewer):
        return None
    scope_ids = set(supervised_users(viewer).exclude(pk=viewer.pk).values_list("pk", flat=True))
    types, submitted_total, missing_total = [], 0, 0
    for rt in ReportType.objects.filter(is_active=True):
        start, end = period_for(rt, ctx.today)
        submitted_ids = set(ReportSubmission.objects
                            .filter(report_type=rt, period_start=start, user_id__in=scope_ids)
                            .values_list("user_id", flat=True))
        required = set(required_users(rt).filter(pk__in=scope_ids).values_list("pk", flat=True))
        unsubmitted = required - submitted_ids
        missing = len(unsubmitted - not_working_ids(unsubmitted, start, end, ctx.today))
        submitted = len(submitted_ids)  # on-time and late, as in the board
        if submitted or missing:
            types.append({"uuid": str(rt.uuid), "name": rt.name,
                          "submitted": submitted, "missing": missing})
            submitted_total += submitted
            missing_total += missing
    return {"submitted": submitted_total, "missing": missing_total, "types": types[:CAP],
            "link": "REPORTS_BOARD"}
