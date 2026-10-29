import datetime as dt
from decimal import Decimal

from apps.attendance.models import PeriodClose
from apps.penalties.services import PenaltyError, create_penalty, void_penalty
from apps.penalties.tests.factories import make_penalty, make_user
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = dt.date


class PenaltyLockTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = make_user("hr", UserTypes.HR, self.department)
        PeriodClose.objects.create(period="2026-09", start=D(2026, 8, 26), end=D(2026, 9, 25),
                                   closed_by=self.superuser, closed_at=dt.datetime(2026, 10, 20, 12))

    def test_create_and_void_refused_on_closed(self):
        data = {"user": self.agent, "penalty_type": None, "title": "Late", "kind": "days",
                "value": Decimal("0.5"), "date": D(2026, 9, 10)}
        with self.assertRaises(PenaltyError) as cm:
            create_penalty(self.hr, data)
        self.assertEqual(cm.exception.type, "period_closed")
        p = make_penalty(self.agent, self.hr, date=D(2026, 9, 10))
        with self.assertRaises(PenaltyError) as cm:
            void_penalty(self.hr, p, "oops")
        self.assertEqual(cm.exception.type, "period_closed")
        p.refresh_from_db()
        self.assertFalse(p.is_voided)

    def test_create_api_returns_400(self):
        self.authenticate_as(self.hr)
        res = self.client.post("/api/penalties/penalties", {
            "user": str(self.agent.uuid), "title": "Late", "kind": "days", "value": "0.5",
            "date": "2026-09-10"}, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        self.assertEqual(res.data["type"], "period_closed")
