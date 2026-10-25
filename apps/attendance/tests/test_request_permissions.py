import datetime as dt

from rest_framework.exceptions import PermissionDenied

from apps.attendance.permissions import can_decide, can_file_for, request_can
from apps.attendance.services import requests as svc
from apps.attendance.tests.factories import make_request
from apps.attendance.tests.test_request_service import RequestServiceBase
from apps.attendance.types import RequestKind as K, RequestStatus as S

D = dt.date
TODAY = D(2026, 10, 25)


class RequestPermissionTests(RequestServiceBase):
    def req(self, user=None, kind=K.GENERAL, start=D(2026, 11, 2), status=S.PENDING, **kw):
        return make_request(user or self.agent, kind, start, status=status, **kw)

    def test_can_decide_matrix(self):
        r = self.req()
        self.assertTrue(can_decide(self.manager, r))
        self.assertFalse(can_decide(self.agent, r))
        self.assertTrue(can_decide(self.hr, r))
        self.assertTrue(can_decide(self.superuser, r))
        self.assertFalse(can_decide(self.manager, self.req(self.outsider)))
        self.assertFalse(can_decide(self.manager, self.req(self.manager)))
        self.assertFalse(can_decide(self.hr, self.req(self.hr)))
        self.assertTrue(can_decide(self.superuser, self.req(self.superuser)))
        self.assertFalse(can_decide(self.agent, self.req(self.agent)))

    def test_over_balance_hr_only(self):
        with self.assertRaises(PermissionDenied):
            svc.approve(self.manager, self.leave(), over_balance=True)

    def test_revoke_hr_only(self):
        r = self.req(status=S.APPROVED)
        with self.assertRaises(PermissionDenied):
            svc.revoke(self.manager, r, "x")
        self.assertEqual(svc.revoke(self.hr, r, "x").status, S.REVOKED)

    def test_can_file_for(self):
        self.assertTrue(can_file_for(self.agent, self.agent))
        self.assertFalse(can_file_for(self.agent, self.manager))
        self.assertTrue(can_file_for(self.manager, self.agent))
        self.assertFalse(can_file_for(self.manager, self.outsider))
        self.assertTrue(can_file_for(self.hr, self.outsider))
        self.assertTrue(can_file_for(self.superuser, self.outsider))

    def flags(self, viewer, r):
        return request_can(viewer, r, TODAY)

    def test_request_can_flags(self):
        pending = self.req()
        f = self.flags(self.agent, pending)
        self.assertEqual(f, {"edit": True, "cancel": True, "request_cancellation": False,
                             "approve": False, "reject": False, "revoke": False})
        f = self.flags(self.manager, pending)
        self.assertEqual((f["edit"], f["cancel"], f["approve"], f["reject"]), (False, False, True, True))
        # on-behalf filer keeps edit/cancel
        behalf = self.req(created_by=self.hr)
        self.assertTrue(self.flags(self.hr, behalf)["edit"])
        self.assertFalse(self.flags(self.outsider, pending)["edit"])

        future = self.req(status=S.APPROVED)
        f = self.flags(self.agent, future)
        self.assertEqual((f["edit"], f["cancel"], f["request_cancellation"], f["approve"], f["revoke"]),
                         (False, True, False, False, False))
        f = self.flags(self.hr, future)
        self.assertEqual((f["revoke"], f["approve"]), (True, False))
        self.assertFalse(self.flags(self.manager, future)["revoke"])

        started = self.req(kind=K.LEAVE, status=S.APPROVED, start=TODAY)
        f = self.flags(self.agent, started)
        self.assertEqual((f["cancel"], f["request_cancellation"]), (False, True))
        general = self.req(kind=K.GENERAL, status=S.APPROVED, start=D(2026, 10, 1))
        self.assertFalse(self.flags(self.agent, general)["request_cancellation"])
        canc = self.req(kind=K.CANCELLATION, status=S.APPROVED, start=D(2026, 11, 2))
        f = self.flags(self.hr, canc)
        self.assertEqual((f["revoke"], f["cancel"]), (False, False))
        self.assertFalse(self.flags(self.agent, canc)["cancel"])
        done = self.req(status=S.REJECTED)
        self.assertFalse(any(self.flags(self.hr, done).values()))
        self.assertFalse(self.flags(self.hr, self.req(self.hr))["approve"])
