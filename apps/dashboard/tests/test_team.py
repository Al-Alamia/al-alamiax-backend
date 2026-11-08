from datetime import date, datetime
from decimal import Decimal

from apps.attendance.models import AttendanceDay
from apps.attendance.tests.factories import make_request
from apps.attendance.types import DayStatus, RequestKind, RequestStatus
from apps.dashboard.registry import build_all
from apps.reports.models import ReportSubmission
from apps.reports.tests.base import ReportsTestCase
from apps.treasury.models import Advance
from apps.treasury.types import AdvanceStatus
from apps.users.models import User
from apps.users.types import UserTypes

NOW = datetime(2026, 11, 10, 12, 0)
TODAY = date(2026, 11, 10)


def widgets(user, now=NOW):
    return build_all(user, now)["widgets"]


class TeamWidgetsTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.superuser.department = None
        self.superuser.save()
        self.manager = self.mk("manager", UserTypes.MANAGER, self.department)
        self.hr = self.mk("hr", UserTypes.HR, self.department)

    def mk(self, name, role=UserTypes.AGENT, department=None):
        u = User.objects.create_user(username=name, password="x", email=f"{name}@t.com",
                                     role=role, project=self.project, department=department)
        User.objects.filter(pk=u.pk).update(date_joined=datetime(2020, 1, 1))
        u.refresh_from_db()
        return u

    def day(self, user, status, late_minutes=0):
        AttendanceDay.objects.create(user=user, date=TODAY, status=status,
                                     late_minutes=late_minutes, evaluated_at=NOW)

    def test_agent_has_no_team_keys(self):
        w = widgets(self.agent)
        for k in ("team_today", "approvals", "team_reports", "payroll_period", "leads", "treasury"):
            self.assertNotIn(k, w)

    def test_manager_team_today_scoped(self):
        late = self.mk("late", department=self.department)
        absent = self.mk("absent", department=self.department)
        self.mk("none", department=self.department)  # no row
        outsider = self.mk("outsider", department=self.marketing)
        self.day(late, DayStatus.LATE, 12)
        self.day(absent, DayStatus.ABSENT)
        self.day(outsider, DayStatus.LATE, 30)
        self.day(self.manager, DayStatus.PRESENT)
        self.day(self.agent, DayStatus.PRESENT)
        t = widgets(self.manager)["team_today"]
        # in scope: agent, hr, late, absent, none (manager excluded)
        self.assertEqual(t["total"], 5)
        self.assertEqual(t["counts"], {"PRESENT": 1, "LATE": 1, "ABSENT": 1, "INCOMPLETE": 0,
                                       "LEAVE": 0, "NONE": 2, "OTHER": 0})
        self.assertEqual(t["late"], [{"uuid": str(late.uuid), "name": "late", "late_minutes": 12}])
        self.assertEqual(t["absent"], [{"uuid": str(absent.uuid), "name": "absent"}])
        self.assertEqual(t["link"], "ATTENDANCE")

    def test_team_today_caps_lists(self):
        for i in range(7):
            self.day(self.mk(f"l{i}", department=self.department), DayStatus.LATE, i + 1)
        t = widgets(self.manager)["team_today"]
        self.assertEqual(t["counts"]["LATE"], 7)
        self.assertEqual(len(t["late"]), 5)
        self.assertEqual(t["late"][0]["late_minutes"], 7)

    def test_manager_without_department_no_team_today(self):
        m = self.mk("nodept", UserTypes.MANAGER, None)
        self.assertNotIn("team_today", widgets(m))

    def test_approvals_counts(self):
        a2 = self.mk("a2", department=self.department)
        make_request(self.agent, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        make_request(a2, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        make_request(a2, RequestKind.GENERAL, date(2026, 11, 11), status=RequestStatus.APPROVED)
        other = self.mk("o", department=self.marketing)
        make_request(other, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        Advance.objects.create(user=self.agent, amount=Decimal("10"), installments=1,
                               start_period="2026-11", status=AdvanceStatus.PENDING)
        Advance.objects.create(user=other, amount=Decimal("10"), installments=1,
                               start_period="2026-11", status=AdvanceStatus.PENDING)
        a = widgets(self.manager)["approvals"]
        self.assertEqual((a["requests"], a["advances"], a["total"]), (2, 1, 3))
        self.assertEqual(a["link"], "ATTENDANCE_APPROVALS")
        self.assertEqual(a["advances_link"], "ADVANCES")

    def test_inactive_user_advance_not_counted(self):
        gone = self.mk("gone", department=self.department)
        Advance.objects.create(user=gone, amount=Decimal("10"), installments=1,
                               start_period="2026-11", status=AdvanceStatus.PENDING)
        gone.is_active = False
        gone.save()
        self.assertEqual(widgets(self.manager)["approvals"]["advances"], 0)

    def test_hr_own_request_not_counted(self):
        make_request(self.hr, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        make_request(self.agent, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        a = widgets(self.hr)["approvals"]
        self.assertEqual(a["requests"], 1)

    def test_approvals_zero_still_shown_for_manager(self):
        a = widgets(self.manager)["approvals"]
        self.assertEqual((a["requests"], a["advances"], a["total"]), (0, 0, 0))

    def test_approvals_absent_for_agent(self):
        self.assertNotIn("approvals", widgets(self.agent))

    def test_team_reports_counts(self):
        rt = self.make_type(departments=[self.department], name="Daily")
        ReportSubmission.objects.create(report_type=rt, user=self.agent, period_start=TODAY,
                                        period_end=TODAY, submitted_at=NOW)
        # manager (viewer) is required too but excluded; hr is the missing one
        r = widgets(self.manager)["team_reports"]
        self.assertEqual((r["submitted"], r["missing"]), (1, 1))
        self.assertEqual(r["types"], [{"uuid": str(rt.uuid), "name": "Daily",
                                       "submitted": 1, "missing": 1}])
        self.assertEqual(r["link"], "REPORTS_BOARD")
        self.assertNotIn("team_reports", widgets(self.agent))
