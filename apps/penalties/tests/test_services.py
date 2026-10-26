from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.attendance.models import AttendanceSettings
from apps.notifications.models import Notification
from apps.penalties.models import Penalty
from apps.penalties.services import PenaltyError, create_penalty, period_total, void_penalty
from apps.penalties.tests.factories import make_penalty, make_type, make_user
from apps.penalties.types import PenaltyKind
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes
from datetime import date


class PenaltyServiceTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = make_user("hr", UserTypes.HR, self.department)
        self.manager = make_user("mgr", UserTypes.MANAGER, self.department)

    def data(self, **kw):
        base = {"user": self.agent, "penalty_type": None, "title": "Late", "kind": PenaltyKind.DAYS,
                "value": Decimal("0.5"), "description": "", "date": timezone.now().date()}
        base.update(kw)
        return base

    def assertErr(self, type_, fn, *a):
        with self.assertRaises(PenaltyError) as cm:
            fn(*a)
        self.assertEqual(cm.exception.type, type_)
        return cm.exception

    def test_create_copies_from_type(self):
        t = make_type(name="Absent", kind=PenaltyKind.MONEY, default_value=Decimal("50"))
        p = create_penalty(self.hr, self.data(penalty_type=t, title="", kind=None, value=None))
        self.assertEqual((p.title, p.kind, p.value, p.penalty_type), ("Absent", "money", Decimal("50"), t))

    def test_create_value_override_kept(self):
        t = make_type()
        p = create_penalty(self.hr, self.data(penalty_type=t, title="", value=Decimal("1.5")))
        self.assertEqual(p.value, Decimal("1.5"))

    def test_create_sent_kind_ignored_with_type(self):
        t = make_type(kind=PenaltyKind.DAYS)
        p = create_penalty(self.hr, self.data(penalty_type=t, kind=PenaltyKind.MONEY))
        self.assertEqual(p.kind, PenaltyKind.DAYS)

    def test_type_rename_does_not_change_penalty(self):
        t = make_type(name="Late")
        p = create_penalty(self.hr, self.data(penalty_type=t, title=""))
        t.name = "Renamed"
        t.default_value = Decimal("9")
        t.save()
        p.refresh_from_db()
        self.assertEqual((p.title, p.value), ("Late", Decimal("0.50")))

    def test_custom_requires_title_kind_value(self):
        for missing in ("title", "kind", "value"):
            self.assertErr("invalid", create_penalty, self.hr, self.data(**{missing: None}))

    def test_future_date_rejected(self):
        self.assertErr("future_date", create_penalty, self.hr,
                       self.data(date=timezone.now().date() + timedelta(days=1)))

    def test_inactive_type_rejected(self):
        t = make_type(is_active=False)
        self.assertErr("inactive_type", create_penalty, self.hr, self.data(penalty_type=t))

    def test_value_zero_invalid(self):
        self.assertErr("invalid", create_penalty, self.hr, self.data(value=Decimal("0")))

    def test_days_two_decimals_invalid(self):
        self.assertErr("invalid", create_penalty, self.hr, self.data(value=Decimal("0.25")))

    def test_days_half_ok(self):
        self.assertEqual(create_penalty(self.hr, self.data(value=Decimal("0.5"))).value, Decimal("0.5"))

    def test_money_two_decimals_ok(self):
        p = create_penalty(self.hr, self.data(kind=PenaltyKind.MONEY, value=Decimal("12.34")))
        self.assertEqual(p.value, Decimal("12.34"))
        self.assertErr("invalid", create_penalty, self.hr,
                       self.data(kind=PenaltyKind.MONEY, value=Decimal("12.345")))

    def test_self_penalty_error_before_forbidden(self):
        self.assertErr("self_penalty", create_penalty, self.manager, self.data(user=self.manager))

    def test_forbidden_status_403(self):
        err = self.assertErr("forbidden", create_penalty, self.agent, self.data(user=self.manager))
        self.assertEqual(err.status, 403)
        self.assertEqual(self.assertErr("invalid", create_penalty, self.hr,
                                        self.data(value=Decimal("0"))).status, 400)

    def test_void_sets_fields(self):
        p = make_penalty(self.agent, self.manager)
        void_penalty(self.hr, p, " wrong ")
        p.refresh_from_db()
        self.assertTrue(p.is_voided)
        self.assertEqual((p.voided_by, p.void_reason), (self.hr, "wrong"))

    def test_void_blank_reason_invalid(self):
        p = make_penalty(self.agent, self.manager)
        self.assertErr("invalid", void_penalty, self.hr, p, "  ")

    def test_void_twice_already_voided(self):
        p = make_penalty(self.agent, self.manager)
        void_penalty(self.hr, p, "x")
        self.assertErr("already_voided", void_penalty, self.hr, p, "x")

    def test_void_forbidden(self):
        p = make_penalty(self.agent, self.manager)
        self.assertErr("forbidden", void_penalty, self.agent, p, "x")

    def _period_data(self):
        make_penalty(self.agent, self.hr, date=date(2026, 9, 25), value=Decimal("1"))
        make_penalty(self.agent, self.hr, date=date(2026, 9, 26), value=Decimal("0.5"))
        make_penalty(self.agent, self.hr, date=date(2026, 10, 25), kind=PenaltyKind.MONEY, value=Decimal("100"))
        make_penalty(self.agent, self.hr, date=date(2026, 10, 26), value=Decimal("2"))

    def test_period_total_start_day_26_boundaries(self):
        s = AttendanceSettings.get()
        s.period_start_day = 26
        s.save()
        self._period_data()
        self.assertEqual(period_total(self.agent, "2026-10"), {
            "period": "2026-10", "start": "2026-09-26", "end": "2026-10-25",
            "days": "0.50", "money": "100.00", "count": 2})

    def test_period_total_start_day_1(self):
        s = AttendanceSettings.get()
        s.period_start_day = 1
        s.save()
        self._period_data()
        self.assertEqual(period_total(self.agent, "2026-10"), {
            "period": "2026-10", "start": "2026-10-01", "end": "2026-10-31",
            "days": "2.00", "money": "100.00", "count": 2})

    def test_period_total_excludes_voided(self):
        make_penalty(self.agent, self.hr, date=date(2026, 10, 1), voided_at=timezone.now())
        self.assertEqual(period_total(self.agent, "2026-10")["count"], 0)
        self.assertEqual(period_total(self.agent, "2026-10")["days"], "0.00")

    def test_period_total_bad_key_raises(self):
        with self.assertRaises(ValueError):
            period_total(self.agent, "2026-13")

    def test_notify_on_create_and_void(self):
        p = create_penalty(self.hr, self.data(value=Decimal("1.5")))
        n = Notification.objects.get(kind="penalty")
        self.assertIn("(1.50 days)", n.message)
        self.assertEqual(n.link, "/penalties")
        void_penalty(self.hr, p, "oops")
        self.assertEqual(Notification.objects.filter(kind="penalty").count(), 2)
        self.assertTrue(Notification.objects.filter(kind="penalty", message__contains="voided").exists())

    def test_no_notify_when_actor_is_user(self):
        create_penalty(self.superuser, self.data(user=self.superuser))
        self.assertFalse(Notification.objects.filter(kind="penalty").exists())
        self.assertEqual(Penalty.objects.count(), 1)
