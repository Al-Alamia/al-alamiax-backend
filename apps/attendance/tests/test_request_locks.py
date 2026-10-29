import datetime as dt

from apps.attendance.models import PeriodClose, Request
from apps.attendance.services import requests as svc
from apps.attendance.tests.factories import make_request
from apps.attendance.tests.test_request_service import NOW, RequestServiceBase
from apps.attendance.tests.test_requests_api import URL
from apps.attendance.types import RequestKind as K, RequestStatus as S

D = dt.date


class RequestLockTests(RequestServiceBase):
    def close(self, key="2026-09", start=D(2026, 8, 26), end=D(2026, 9, 25)):
        return PeriodClose.objects.create(period=key, start=start, end=end,
                                          closed_by=self.superuser, closed_at=NOW)

    def inside(self, status, user=None):
        return make_request(user or self.agent, K.GENERAL, D(2026, 9, 10), status=status, details="x")

    def test_submit_spanning_closed_period_refused(self):
        self.close()
        self.assertEqual(self.code(self.leave, D(2026, 9, 24), D(2026, 9, 28)), "period_closed")
        self.assertEqual(Request.objects.count(), 0)

    def test_submit_api_returns_400(self):
        self.close()
        self.authenticate_as(self.agent)
        res = self.client.post(URL, {"kind": "LEAVE", "start_date": "2026-09-24", "end_date": "2026-09-28",
                                     "leave_type": str(self.annual.uuid)}, format="json")
        self.assertEqual(res.status_code, 400, res.data)
        self.assertEqual(res.data["type"], "period_closed")

    def test_approve_and_edit_refused_on_closed(self):
        req = self.inside(S.PENDING)
        self.close()
        self.assertEqual(self.code(svc.approve, self.hr, req), "period_closed")
        self.assertEqual(self.code(svc.edit, self.agent, req,
                                   {"kind": K.GENERAL, "start_date": D(2026, 9, 10), "details": "y"}),
                         "period_closed")

    def test_edit_moving_into_closed_refused(self):
        req = self.inside(S.PENDING)
        req.start_date = req.end_date = D(2026, 11, 2)
        req.save()
        self.close()
        self.assertEqual(self.code(svc.edit, self.agent, req,
                                   {"kind": K.GENERAL, "start_date": D(2026, 9, 10), "details": "y"}),
                         "period_closed")

    def test_cancel_and_revoke_refused_on_closed(self):
        req = self.inside(S.APPROVED)
        self.close()
        self.assertEqual(self.code(svc.cancel, self.agent, req), "period_closed")
        self.assertEqual(self.code(svc.revoke, self.hr, req, "note"), "period_closed")
        req.refresh_from_db()
        self.assertEqual(req.status, S.APPROVED)

    def test_reject_pending_succeeds_on_closed(self):
        req = self.inside(S.PENDING)
        self.close()
        self.assertEqual(svc.reject(self.hr, req, "no").status, S.REJECTED)

    def test_open_period_unaffected(self):
        self.assertEqual(self.leave(D(2026, 9, 24), D(2026, 9, 28)).status, S.PENDING)
