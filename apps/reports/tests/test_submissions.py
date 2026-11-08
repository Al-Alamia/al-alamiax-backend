from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.attendance.models import PeriodClose
from apps.reports.errors import ReportError
from apps.reports.models import ReportSubmission
from apps.reports.services import submissions
from apps.reports.tests.base import ReportsTestCase
from apps.users.models import Department, User
from apps.users.types import UserTypes


class SubmissionTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.u = User.objects.create_user(
            username="mk1", password="x", role=UserTypes.AGENT, department=self.marketing,
            project=self.project)
        self.rt = self.make_type("daily")
        self.today = date(2026, 11, 8)
        self.f = {f.label: str(f.uuid) for f in self._fields(self.rt)}

    def _fields(self, rt):
        from apps.reports.models import ReportField
        return ReportField.objects.filter(section__report_type=rt)

    def save(self, values, d=None, rt=None, user=None, today=None):
        return submissions.save_submission(
            rt or self.rt, user or self.u, d or self.today, values, today or self.today)

    def assertError(self, type_, fn, *a, **kw):
        with self.assertRaises(ReportError) as cm:
            fn(*a, **kw)
        self.assertEqual(cm.exception.type, type_)
        return cm.exception

    def test_submit_creates_and_snapshots(self):
        s = self.save({self.f["n"]: 5, self.f["t"]: "hi"})
        self.assertEqual(s.department, self.marketing)
        self.assertEqual(s.project, self.project)
        self.assertFalse(s.is_late)
        self.assertEqual(s.period_start, self.today)
        vals = submissions.submission_values(s)
        self.assertEqual(vals[self.f["n"]], "5.00")
        self.assertEqual(vals[self.f["t"]], "hi")

    def test_snapshot_only_at_first_submit(self):
        s = self.save({self.f["n"]: 5})
        other = Department.objects.create(name="Other", code="other")
        self.u.department = other
        self.u.save()
        s = self.save({self.f["n"]: 6})
        self.assertEqual(s.department, self.marketing)

    def test_submit_mid_period_updates_same_submission(self):
        rt = self.make_type("weekly")
        f = {x.label: str(x.uuid) for x in self._fields(rt)}
        a = submissions.save_submission(rt, self.u, date(2026, 11, 8), {f["n"]: 1, f["t"]: "x"}, self.today)
        b = submissions.save_submission(rt, self.u, date(2026, 11, 10), {f["n"]: 2}, self.today)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(ReportSubmission.objects.filter(report_type=rt).count(), 1)
        self.assertEqual(b.period_start, date(2026, 11, 7))
        vals = submissions.submission_values(b)
        self.assertEqual(vals[f["n"]], "2.00")
        self.assertNotIn(f["t"], vals)

    def test_late_flag(self):
        s = self.save({self.f["n"]: 1}, d=date(2026, 11, 6))
        self.assertTrue(s.is_late)
        s = self.save({self.f["n"]: 2}, d=date(2026, 11, 6))
        self.assertTrue(s.is_late)
        # edit after the period ended marks an on-time submission late
        s2 = self.save({self.f["n"]: 1}, d=self.today)
        self.assertFalse(s2.is_late)
        s2 = self.save({self.f["n"]: 2}, d=self.today, today=self.today + timedelta(days=1))
        self.assertTrue(s2.is_late)

    def test_refusals(self):
        self.assertError("future", self.save, {self.f["n"]: 1}, d=self.today + timedelta(days=1))
        d = date(2026, 11, 1)
        PeriodClose.objects.create(period="2026-11", start=date(2026, 10, 26), end=date(2026, 11, 25),
                                   closed_by=self.superuser, closed_at=timezone.now())
        self.assertError("period_closed", self.save, {self.f["n"]: 1}, d=d)
        PeriodClose.objects.all().delete()
        rt = self.make_type("daily", edit_window_days=2)
        f = {x.label: str(x.uuid) for x in self._fields(rt)}
        self.assertError("window_passed", self.save, {f["n"]: 1}, d=self.today - timedelta(days=5), rt=rt)
        self.save({f["n"]: 1}, d=self.today - timedelta(days=2), rt=rt)
        off = self.make_type("daily", is_active=False)
        self.assertError("inactive", self.save, {}, rt=off)
        out = User.objects.create_user(username="x1", password="x", department=self.department)
        self.assertError("not_assigned", self.save, {self.f["n"]: 1}, user=out)

    def test_not_assigned_but_existing_submission_can_edit(self):
        self.save({self.f["n"]: 1})
        self.rt.excluded_users.add(self.u)
        ok, reason = submissions.can_edit(self.rt, self.u, self.today, self.today, self.today)
        self.assertTrue(ok)
        self.assertIsNone(reason)
        ok, reason = submissions.can_edit(
            self.rt, self.u, self.today - timedelta(days=1), self.today - timedelta(days=1), self.today)
        self.assertEqual((ok, reason), (False, "not_assigned"))

    def test_required_fields(self):
        e = self.assertError("invalid", self.save, {self.f["t"]: "x"})
        self.assertIn(self.f["n"], e.fields)
        rt = self.make_type("daily", sections=[("S", [("a", "accounts", True)])])
        f = {x.label: str(x.uuid) for x in self._fields(rt)}
        e = self.assertError("invalid", self.save, {f["a"]: []}, rt=rt)
        self.assertIn(f["a"], e.fields)

    def test_number_validation(self):
        s = self.save({self.f["n"]: 1, self.f["t"]: ""})
        self.assertEqual(submissions.submission_values(s)[self.f["t"]], "")
        rt = self.make_type("daily", sections=[("S", [("n", "number", False)])])
        f = {x.label: str(x.uuid) for x in self._fields(rt)}
        s = self.save({f["n"]: ""}, rt=rt)
        self.assertIsNone(s.values.get().number)
        s = self.save({f["n"]: "12.5"}, rt=rt)
        self.assertEqual(s.values.get().number, Decimal("12.5"))
        for bad in (-1, "abc", "NaN", True, 10 ** 10, [1]):
            e = self.assertError("invalid", self.save, {f["n"]: bad}, rt=rt)
            self.assertIn(f["n"], e.fields)

    def test_unknown_and_inactive_field_rejected(self):
        import uuid
        ghost = str(uuid.uuid4())
        e = self.assertError("invalid", self.save, {self.f["n"]: 1, ghost: 1})
        self.assertIn(ghost, e.fields)
        other = self.make_type("daily")
        of = str(self._fields(other).first().uuid)
        self.assertError("invalid", self.save, {self.f["n"]: 1, of: 1})
        from apps.reports.models import ReportField
        ReportField.objects.filter(uuid=self.f["t"]).update(is_active=False)
        e = self.assertError("invalid", self.save, {self.f["n"]: 1, self.f["t"]: "x"})
        self.assertIn(self.f["t"], e.fields)

    def test_accounts_cleaned(self):
        s = self.save({self.f["n"]: 1, self.f["a"]: [" a ", "", "  ", "b"]})
        self.assertEqual(submissions.submission_values(s)[self.f["a"]], ["a", "b"])
        e = self.assertError("invalid", self.save, {self.f["n"]: 1, self.f["a"]: ["x"] * 51})
        self.assertIn(self.f["a"], e.fields)
        self.assertError("invalid", self.save, {self.f["n"]: 1, self.f["a"]: ["x" * 101]})
        self.assertError("invalid", self.save, {self.f["n"]: 1, self.f["a"]: "abc"})
