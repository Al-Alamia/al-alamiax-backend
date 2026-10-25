import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.attendance.models import LeaveAllowance, LeaveType, Request
from apps.attendance.types import RequestKind, RequestStatus
from apps.users.tests.base import BaseUserTestCase


class RequestModelsTests(BaseUserTestCase):
    def _type(self, name="Annual"):
        return LeaveType.objects.create(
            name=name, pay_percent=100, uses_balance=True, yearly_allowance=Decimal("21"))

    def test_leave_allowance_unique_per_user_type_year(self):
        leave_type = self._type()
        LeaveAllowance.objects.create(
            user=self.agent, leave_type=leave_type, year=2026, days=Decimal("10"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            LeaveAllowance.objects.create(
                user=self.agent, leave_type=leave_type, year=2026, days=Decimal("5"))
        LeaveAllowance.objects.create(
            user=self.agent, leave_type=leave_type, year=2027, days=Decimal("5"))

    def test_leave_type_protected_when_used(self):
        leave_type = self._type()
        day = datetime.date(2026, 10, 5)
        req = Request.objects.create(
            user=self.agent, kind=RequestKind.LEAVE, start_date=day, end_date=day,
            leave_type=leave_type)
        self.assertEqual(req.status, RequestStatus.PENDING)
        with self.assertRaises(ProtectedError):
            leave_type.delete()

    def test_old_request_route_gone(self):
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.get("/api/users/request").status_code, 404)
