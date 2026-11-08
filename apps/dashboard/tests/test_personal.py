from datetime import date, datetime, timedelta
from decimal import Decimal

from apps.attendance.models import AttendanceDay
from apps.attendance.tests.factories import make_request
from apps.attendance.types import DayStatus, RequestKind, RequestStatus
from apps.dashboard.registry import build_all
from apps.notifications.models import Notification, NotificationRecipient
from apps.reports.models import ReportSubmission
from apps.reports.tests.base import ReportsTestCase
from apps.salaries.models import Salary
from apps.salaries.types import SalaryStatus
from apps.treasury.models import Advance, AdvanceInstallment
from apps.treasury.types import AdvanceStatus

NOW = datetime(2026, 11, 10, 12, 0)  # period 2026-11 = 2026-10-26 .. 2026-11-25


def widgets(user, now=NOW):
    return build_all(user, now)["widgets"]


class PersonalWidgetsTests(ReportsTestCase):
    def day(self, offset, status, user=None):
        AttendanceDay.objects.create(
            user=user or self.agent, date=date(2026, 10, 26) + timedelta(days=offset),
            status=status, evaluated_at=NOW)

    def test_new_agent_minimal_keys(self):
        w = widgets(self.agent)
        self.assertEqual(set(w), {"attendance_period", "my_requests", "notifications"})
        self.assertEqual(w["attendance_period"]["late_percent"], 0)
        self.assertEqual(w["attendance_period"]["working_days"], 0)
        self.assertEqual(w["attendance_period"]["link"], "ATTENDANCE")
        self.assertEqual(w["my_requests"]["link"], "ATTENDANCE_REQUESTS")
        self.assertEqual(w["notifications"]["link"], "NOTIFICATIONS")

    def test_late_percent(self):
        S = DayStatus
        for i, s in enumerate([S.PRESENT, S.PRESENT, S.LATE, S.ABSENT, S.WEEKEND, S.WEEKEND,
                               S.LEAVE, S.HOLIDAY, S.EXCUSED]):
            self.day(i, s)
        # a day after today must not count
        AttendanceDay.objects.create(user=self.agent, date=date(2026, 11, 20), status=S.ABSENT,
                                     evaluated_at=NOW)
        a = widgets(self.agent)["attendance_period"]
        self.assertEqual(
            {k: a[k] for k in ("working_days", "present", "late", "absent", "leave", "late_percent")},
            {"working_days": 4, "present": 2, "late": 1, "absent": 1, "leave": 1, "late_percent": 25.0})

    def test_my_requests_pending_and_cap(self):
        for i in range(7):
            make_request(self.agent, RequestKind.GENERAL, date(2026, 11, 1) + timedelta(days=i),
                         status=RequestStatus.PENDING if i in (1, 3, 5) else RequestStatus.APPROVED)
        r = widgets(self.agent)["my_requests"]
        self.assertEqual(r["pending_count"], 3)
        self.assertEqual(len(r["latest"]), 5)
        self.assertEqual(r["latest"][0]["start_date"], "2026-11-07")
        self.assertEqual(set(r["latest"][0]), {"uuid", "kind", "status", "start_date", "end_date"})

    def test_notifications_unread_and_cap(self):
        for i in range(7):
            n = Notification.objects.create(title=f"t{i}", message="m")
            NotificationRecipient.objects.create(
                notification=n, user=self.agent, read_at=NOW if i < 2 else None)
        w = widgets(self.agent)["notifications"]
        self.assertEqual(w["unread_count"], 5)
        self.assertEqual(len(w["latest"]), 5)
        self.assertEqual(w["latest"][0]["title"], "t6")
        self.assertIs(w["latest"][0]["read"], False)

    def test_my_salary_latest_given(self):
        def mk(period, status):
            return Salary.objects.create(
                user=self.agent, period=period, status=status, basic_net=Decimal("100"),
                commission=Decimal("5"), total=Decimal("105"), given_at=NOW)
        mk("2026-08", SalaryStatus.GIVEN)
        mk("2026-09", SalaryStatus.GIVEN)
        mk("2026-10", SalaryStatus.DRAFT)
        s = widgets(self.agent)["my_salary"]
        self.assertEqual(s["period"], "2026-09")
        self.assertEqual(s["total"], "105.00")
        self.assertEqual(s["link"], "MY_SALARY")

    def test_my_reports_due_only_missing_editable(self):
        rt = self.make_type(departments=[self.department], edit_window_days=1, name="Daily")
        self.make_type(departments=[self.marketing], name="Other")
        today, yesterday = date(2026, 11, 10), date(2026, 11, 9)
        ReportSubmission.objects.create(report_type=rt, user=self.agent, period_start=yesterday,
                                        period_end=yesterday, submitted_at=NOW)
        r = widgets(self.agent)["my_reports"]
        self.assertEqual(r["due_count"], 1)
        self.assertEqual(r["due"], [{"type_uuid": str(rt.uuid), "name": "Daily",
                                     "period_start": today.isoformat(),
                                     "period_end": today.isoformat()}])
        self.assertEqual(r["link"], "REPORTS")
        self.superuser.department = None
        self.superuser.save()
        self.assertNotIn("my_reports", widgets(self.superuser))

    def test_my_advances_pending_and_outstanding(self):
        self.assertNotIn("my_advances", widgets(self.agent))
        done = Advance.objects.create(user=self.agent, amount=Decimal("300"), installments=3,
                                      start_period="2026-10", status=AdvanceStatus.APPROVED)
        for p in ("2026-10", "2026-11", "2026-12"):
            AdvanceInstallment.objects.create(advance=done, period=p, amount=Decimal("100"))
        pend = Advance.objects.create(user=self.agent, amount=Decimal("50"), installments=1,
                                      start_period="2027-01", status=AdvanceStatus.PENDING)
        a = widgets(self.agent)["my_advances"]
        self.assertEqual(a["outstanding"], "200.00")
        self.assertEqual(a["pending"], {"uuid": str(pend.uuid), "amount": "50.00",
                                        "installments": 1, "start_period": "2027-01"})
        self.assertEqual(a["link"], "ADVANCES")
