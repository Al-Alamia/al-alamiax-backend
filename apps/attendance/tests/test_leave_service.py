import datetime as dt
from decimal import Decimal

from apps.attendance.models import Holiday, LeaveAllowance
from apps.attendance.services import leave
from apps.attendance.services.evaluate import recalculate
from apps.attendance.tests.factories import (
    assign, make_leave_type, make_policy, make_request, make_shift,
)
from apps.attendance.types import RequestKind, RequestStatus
from apps.users.tests.base import BaseUserTestCase

D = dt.date
NOW = dt.datetime(2026, 10, 20, 12)


class LeaveServiceTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        make_policy()
        self.shift = make_shift(weekend_days=[4, 5])  # Fri, Sat
        assign(self.shift, department=self.department, effective_from=D(2026, 10, 5))

    def lt(self, **kw):
        kw.setdefault("uses_balance", True)
        kw.setdefault("yearly_allowance", 21)
        return make_leave_type(**kw)

    def leave_req(self, lt, start, end=None, status=RequestStatus.APPROVED):
        return make_request(self.agent, RequestKind.LEAVE, start, end, status=status, leave_type=lt)

    def test_working_dates_skips_weekend_holiday_no_shift(self):
        Holiday.objects.create(date=D(2026, 10, 7), name="H", department=self.department)
        # Oct 1-4 before assignment; 5 Mon, 6 Tue, 7 holiday, 8 Thu, 9 Fri, 10 Sat, 11 Sun
        got = leave.working_dates(self.agent, D(2026, 10, 1), D(2026, 10, 11))
        self.assertEqual(got, [D(2026, 10, 5), D(2026, 10, 6), D(2026, 10, 8), D(2026, 10, 11)])

    def test_working_dates_matches_evaluate_across_shift_change(self):
        assign(make_shift(weekend_days=[6]), user=self.agent, effective_from=D(2026, 10, 8))
        lt = self.lt()
        req = self.leave_req(lt, D(2026, 10, 5), D(2026, 10, 14))
        recalculate(D(2026, 10, 5), D(2026, 10, 14), [self.agent], NOW)
        req.refresh_from_db()
        self.assertEqual(len(leave.working_dates(self.agent, req.start_date, req.end_date)),
                         req.leave_days)

    def test_working_dates_skips_before_date_joined(self):
        self.agent.date_joined = dt.datetime(2026, 10, 6)
        self.assertEqual(leave.working_dates(self.agent, D(2026, 10, 5), D(2026, 10, 6)),
                         [D(2026, 10, 6)])

    def test_allowance_default_and_override(self):
        lt = self.lt()
        LeaveAllowance.objects.create(user=self.agent, leave_type=lt, year=2026, days=25)
        self.assertEqual(leave.allowance(self.agent, lt, 2026), Decimal("25"))
        self.assertEqual(leave.allowance(self.agent, lt, 2027), Decimal("21"))

    def test_used_and_remaining(self):
        lt = self.lt()
        self.leave_req(lt, D(2026, 10, 5), D(2026, 10, 7))
        self.leave_req(lt, D(2026, 10, 12), D(2026, 10, 13), status=RequestStatus.PENDING)
        self.leave_req(lt, D(2026, 10, 19), D(2026, 10, 20), status=RequestStatus.REVOKED)
        recalculate(D(2026, 10, 5), D(2026, 10, 7), [self.agent], NOW)
        self.assertEqual(leave.used(self.agent, lt, 2026), Decimal("3"))
        self.assertEqual(leave.pending(self.agent, lt, 2026), Decimal("2"))
        self.assertEqual(leave.remaining(self.agent, lt, 2026), Decimal("18"))
        self.assertEqual(leave.used(self.agent, lt, 2025), Decimal("0"))

    def test_exclude_leaves_request_out(self):
        lt = self.lt()
        req = self.leave_req(lt, D(2026, 10, 5), D(2026, 10, 7))
        recalculate(D(2026, 10, 5), D(2026, 10, 7), [self.agent], NOW)
        self.assertEqual(leave.used(self.agent, lt, 2026, exclude=req), Decimal("0"))
        self.assertEqual(leave.remaining(self.agent, lt, 2026, exclude=req), Decimal("21"))

    def test_balances_lists_only_active_balance_types(self):
        lt = self.lt(name="Annual")
        self.lt(name="Inactive", is_active=False)
        self.lt(name="Unlimited", uses_balance=False)
        rows = leave.balances(self.agent, 2026)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"leave_type": {"uuid": lt.uuid, "name": "Annual"},
                                   "allowance": Decimal("21"), "used": Decimal("0"),
                                   "pending": Decimal("0"), "remaining": Decimal("21")})
