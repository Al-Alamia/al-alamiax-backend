import uuid
from datetime import date, datetime as dt

from unittest import mock

from apps.attendance.models import AttendanceDay
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

DAYS = "/api/attendance/days"
DAILY = "/api/attendance/days/daily"
RECALC = "/api/attendance/recalculate"
NOW = dt(2026, 10, 21, 12, 0, 0)


def make_day(user, d, status, deduction=0.0, late=0, early=0):
    return AttendanceDay.objects.create(
        user=user, date=d, status=status, deduction_days=deduction, late_minutes=late,
        early_leave_minutes=early, evaluated_at=NOW)


class FrozenNowMixin:
    def setUp(self):
        super().setUp()
        patcher = mock.patch("apps.attendance.views.days._now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)


class PeriodDaysTests(FrozenNowMixin, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        make_day(self.agent, date(2026, 10, 2), "ABSENT", 1.0)
        make_day(self.agent, date(2026, 10, 1), "PRESENT")
        make_day(self.agent, date(2026, 10, 3), "LATE", 0.25, late=30, early=5)
        make_day(self.agent, date(2026, 9, 25), "PRESENT")  # previous period
        self.authenticate_as(self.agent)

    def test_summary_and_period(self):
        r = self.client.get(DAYS, {"period": "2026-10"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["period"], {"key": "2026-10", "start": "2026-09-26", "end": "2026-10-25"})
        s = r.data["summary"]
        self.assertEqual((s["present"], s["late"], s["absent"]), (1, 1, 1))
        self.assertEqual(s["deduction_days"], 1.25)
        self.assertEqual(s["on_time_percent"], 50.0)
        self.assertEqual((s["late_minutes"], s["early_leave_minutes"]), (30, 5))
        self.assertEqual(r.data["user"]["username"], "agent")

    def test_results_ordered_by_date_and_in_period(self):
        r = self.client.get(DAYS, {"period": "2026-10"})
        self.assertEqual([d["date"] for d in r.data["results"]], ["2026-10-01", "2026-10-02", "2026-10-03"])

    def test_default_period_is_current(self):
        r = self.client.get(DAYS)
        self.assertEqual(r.data["period"]["key"], "2026-10")

    def test_bad_period_is_400(self):
        r = self.client.get(DAYS, {"period": "bad"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_period"))

    def test_other_user_forbidden_for_agent(self):
        r = self.client.get(DAYS, {"user": str(self.superuser.uuid)})
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))

    def test_invalid_user(self):
        r = self.client.get(DAYS, {"user": "nope"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_user"))

    def test_hr_views_other_and_zero_percent(self):
        self.authenticate_as(self.superuser)
        r = self.client.get(DAYS, {"user": str(self.agent.uuid), "period": "2026-09"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["summary"]["on_time_percent"], 100.0)
        r = self.client.get(DAYS, {"user": str(self.superuser.uuid)})
        self.assertEqual(r.data["summary"]["on_time_percent"], 0)

    def test_manager_other_department_forbidden(self):
        other = Department.objects.create(name="Other")
        manager = User.objects.create_user(username="mgr", password="x", role=UserTypes.MANAGER,
                                           project=self.project, department=other)
        self.authenticate_as(manager)
        r = self.client.get(DAYS, {"user": str(self.agent.uuid)})
        self.assertEqual(r.status_code, 403)


class DailyTests(FrozenNowMixin, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.objects.create(name="Other")
        self.other = User.objects.create_user(username="other", password="x", role=UserTypes.AGENT,
                                              project=self.project, department=self.other_dept)
        self.d = date(2026, 10, 21)
        make_day(self.agent, self.d, "LATE", 0.25, late=20)
        make_day(self.superuser, self.d, "PRESENT")

    def test_agent_forbidden(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(DAILY).status_code, 403)

    def test_hr_sees_all_with_counts(self):
        self.authenticate_as(self.superuser)
        r = self.client.get(DAILY, {"date": "2026-10-21"})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["date"], "2026-10-21")
        self.assertEqual(len(r.data["results"]), 3)
        c = r.data["counts"]
        self.assertEqual((c["NONE"], c["LATE"], c["PRESENT"], c["ABSENT"], c["NO_SHIFT"]), (1, 1, 1, 0, 0))
        self.assertEqual(len(c), 8)
        none = [x for x in r.data["results"] if x["day"] is None]
        self.assertEqual(none[0]["user"]["username"], "other")

    def test_default_date_today(self):
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.get(DAILY).data["date"], "2026-10-21")

    def test_invalid_date(self):
        self.authenticate_as(self.superuser)
        r = self.client.get(DAILY, {"date": "x"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_date"))

    def test_status_filter(self):
        self.authenticate_as(self.superuser)
        r = self.client.get(DAILY, {"date": "2026-10-21", "status": "LATE"})
        self.assertEqual([x["user"]["username"] for x in r.data["results"]], ["agent"])
        r = self.client.get(DAILY, {"date": "2026-10-21", "status": "NONE"})
        self.assertEqual([x["user"]["username"] for x in r.data["results"]], ["other"])
        self.assertEqual(r.data["counts"]["LATE"], 1)
        r = self.client.get(DAILY, {"status": "BOGUS"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_status"))

    def test_hr_department_filter(self):
        self.authenticate_as(self.superuser)
        r = self.client.get(DAILY, {"date": "2026-10-21", "department": str(self.other_dept.uuid)})
        self.assertEqual([x["user"]["username"] for x in r.data["results"]], ["other"])
        r = self.client.get(DAILY, {"department": "nope"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_department"))

    def test_manager_scope(self):
        mgr = User.objects.create_user(username="mgr", password="x", role=UserTypes.MANAGER,
                                       project=self.project, department=self.other_dept)
        self.authenticate_as(mgr)
        r = self.client.get(DAILY, {"date": "2026-10-21"})
        self.assertEqual(sorted(x["user"]["username"] for x in r.data["results"]), ["mgr", "other"])
        r = self.client.get(DAILY, {"department": str(self.department.uuid)})
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        r = self.client.get(DAILY, {"department": str(self.other_dept.uuid)})
        self.assertEqual(r.status_code, 200)


class RecalculateTests(FrozenNowMixin, BaseUserTestCase):
    def body(self, **kw):
        return {"from": "2026-10-19", "to": "2026-10-20", **kw}

    def test_agent_forbidden(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.post(RECALC, self.body(), format="json").status_code, 403)

    def test_manager_forbidden(self):
        mgr = User.objects.create_user(username="mgr", password="x", role=UserTypes.MANAGER,
                                       project=self.project, department=self.department)
        self.authenticate_as(mgr)
        self.assertEqual(self.client.post(RECALC, self.body(), format="json").status_code, 403)

    def test_range_too_long(self):
        self.authenticate_as(self.superuser)
        r = self.client.post(RECALC, {"from": "2026-08-01", "to": "2026-10-02"}, format="json")  # 63 days
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_range"))

    def test_62_days_ok_and_reversed_bad(self):
        self.authenticate_as(self.superuser)
        r = self.client.post(RECALC, {"from": "2026-08-01", "to": "2026-10-01"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.client.post(RECALC, {"from": "2026-10-02", "to": "2026-10-01"}, format="json")
        self.assertEqual(r.data["type"], "invalid_range")
        r = self.client.post(RECALC, {"from": "x", "to": "2026-10-01"}, format="json")
        self.assertEqual(r.data["type"], "invalid_range")

    def test_hr_updates(self):
        from apps.attendance.tests.factories import assign, make_shift
        assign(make_shift(weekend_days=[]), department=self.department)
        self.authenticate_as(self.superuser)
        r = self.client.post(RECALC, self.body(), format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertGreaterEqual(r.data["updated"], 1)

    def test_user_and_department_limits(self):
        from apps.attendance.tests.factories import assign, make_shift
        assign(make_shift(weekend_days=[]), department=self.department)
        self.authenticate_as(self.superuser)
        r = self.client.post(RECALC, self.body(user=str(self.agent.uuid)), format="json")
        self.assertEqual(r.data["updated"], 2)
        r = self.client.post(RECALC, self.body(department=str(uuid.uuid4())), format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_department"))
        r = self.client.post(RECALC, self.body(user=str(uuid.uuid4())), format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_user"))
        r = self.client.post(RECALC, self.body(user="bad"), format="json")
        self.assertEqual(r.data["type"], "invalid_user")
        r = self.client.post(RECALC, self.body(department="bad"), format="json")
        self.assertEqual(r.data["type"], "invalid_department")
