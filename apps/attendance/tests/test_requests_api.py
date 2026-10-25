import datetime as dt
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.attendance.models import AttendanceDay
from apps.attendance.services import requests as svc
from apps.attendance.tests.factories import assign, make_leave_type, make_policy, make_request, make_shift
from apps.attendance.types import RequestKind as K, RequestStatus as S
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = dt.date
NOW = dt.datetime(2026, 10, 25, 12)  # Sunday
URL = "/api/attendance/requests"


class RequestsApiBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(svc, "_now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        make_policy()
        assign(make_shift(weekend_days=[4, 5]), department=self.department)
        self.other_dept = Department.objects.create(name="Other")
        assign(make_shift(), department=self.other_dept)
        self.manager = self.mkuser("manager", UserTypes.MANAGER)
        self.hr = self.mkuser("hr", UserTypes.HR)
        self.outsider = self.mkuser("outsider", UserTypes.AGENT, self.other_dept)
        self.annual = make_leave_type(name="Annual", uses_balance=True, yearly_allowance=21)

    def mkuser(self, name, role, dept=None):
        u = User.objects.create_user(username=name, password="x", email=f"{name}@t.com", role=role,
                                     project=self.project, department=dept or self.department)
        User.objects.filter(pk=u.pk).update(date_joined=dt.datetime(2020, 1, 1))
        u.refresh_from_db()
        return u

    def pending(self, user, kind=K.GENERAL, start=D(2026, 11, 2), **kw):
        kw.setdefault("details", "x")
        return make_request(user, kind, start, status=S.PENDING, **kw)

    def uuids(self, res):
        return {r["uuid"] for r in res.data["results"]}


class ListTests(RequestsApiBase):
    def test_agent_lists_only_own(self):
        mine = self.pending(self.agent)
        self.pending(self.outsider)
        self.pending(self.manager)
        self.authenticate_as(self.agent)
        res = self.client.get(URL)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.uuids(res), {str(mine.uuid)})
        self.assertEqual(res.data["count"], 1)

    def test_manager_scope_approvals(self):
        theirs = self.pending(self.agent)
        self.pending(self.manager)
        self.pending(self.outsider)
        make_request(self.agent, K.GENERAL, D(2026, 11, 3), status=S.APPROVED, details="x")
        self.authenticate_as(self.manager)
        res = self.client.get(URL, {"scope": "approvals"})
        self.assertEqual(self.uuids(res), {str(theirs.uuid)})
        self.assertEqual(res.data["count"], 1)

    def test_hr_lists_all_with_filters(self):
        a = make_request(self.agent, K.LEAVE, D(2026, 11, 2), status=S.APPROVED, leave_type=self.annual)
        b = self.pending(self.outsider, K.GENERAL, D(2026, 12, 1))
        self.authenticate_as(self.hr)
        self.assertEqual(self.uuids(self.client.get(URL)), {str(a.uuid), str(b.uuid)})
        self.assertEqual(self.uuids(self.client.get(URL, {"kind": "LEAVE"})), {str(a.uuid)})
        self.assertEqual(self.uuids(self.client.get(URL, {"status": "PENDING"})), {str(b.uuid)})
        res = self.client.get(URL, {"date_from": "2026-11-15", "date_to": "2026-12-31"})
        self.assertEqual(self.uuids(res), {str(b.uuid)})
        self.assertEqual(self.client.get(URL, {"date_from": "bad"}).status_code, 400)
        self.assertEqual(self.uuids(self.client.get(URL, {"user": str(self.outsider.uuid)})), {str(b.uuid)})


class SubmitTests(RequestsApiBase):
    def post_leave(self, **extra):
        data = {"kind": "LEAVE", "start_date": "2026-11-02", "end_date": "2026-11-03",
                "leave_type": str(self.annual.uuid), "minutes": "", "punch_time": ""}
        data.update(extra)
        return self.client.post(URL, data, format="multipart")

    def test_submit_multipart_with_attachment(self):
        self.authenticate_as(self.agent)
        f = SimpleUploadedFile("a.pdf", b"x" * 10, content_type="application/pdf")
        res = self.post_leave(attachment=f)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertTrue(res.data["attachment"].startswith("http"))
        self.assertTrue(res.data["attachment"].endswith(".pdf") or ".pdf" in res.data["attachment"])
        self.assertEqual(res.data["leave_type"]["name"], "Annual")
        self.assertEqual(res.data["days"], [])
        self.assertTrue(res.data["can"]["edit"])

    def test_submit_json(self):
        self.authenticate_as(self.agent)
        res = self.client.post(URL, {"kind": "GENERAL", "start_date": "2026-11-02", "details": "hi"},
                               format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNone(res.data["attachment"])

    def test_submit_rejects_large_or_bad_file(self):
        self.authenticate_as(self.agent)
        big = SimpleUploadedFile("a.pdf", b"x" * (6 * 1024 * 1024), content_type="application/pdf")
        res = self.post_leave(attachment=big)
        self.assertEqual((res.status_code, res.data["type"]), (400, "validation"))
        txt = SimpleUploadedFile("a.txt", b"x", content_type="text/plain")
        res = self.post_leave(attachment=txt)
        self.assertEqual((res.status_code, res.data["type"]), (400, "validation"))

    def test_submit_for_other_user_forbidden_for_agent(self):
        self.authenticate_as(self.agent)
        res = self.client.post(URL, {"kind": "GENERAL", "start_date": "2026-11-02", "details": "hi",
                                     "user": str(self.outsider.uuid)}, format="json")
        self.assertEqual((res.status_code, res.data["type"]), (403, "forbidden"))

    def test_submit_on_behalf_by_manager(self):
        self.authenticate_as(self.manager)
        res = self.client.post(URL, {"kind": "GENERAL", "start_date": "2026-11-02", "details": "hi",
                                     "user": str(self.agent.uuid)}, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["user"]["uuid"], str(self.agent.uuid))
        self.assertEqual(res.data["created_by"]["uuid"], str(self.manager.uuid))

    def test_submit_bad_input_400(self):
        self.authenticate_as(self.agent)
        res = self.client.post(URL, {"kind": "GENERAL", "start_date": "nope"}, format="json")
        self.assertEqual((res.status_code, res.data["type"]), (400, "validation"))
        res = self.client.post(URL, {"kind": "LEAVE", "start_date": "2026-11-02", "leave_type": "zzz"},
                               format="json")
        self.assertEqual(res.status_code, 400)


class DetailAndActionTests(RequestsApiBase):
    def test_detail_out_of_scope_404(self):
        req = self.pending(self.outsider)
        self.authenticate_as(self.agent)
        for path in ("", "/approve", "/reject", "/cancel", "/revoke"):
            res = (self.client.get if not path else self.client.post)(f"{URL}/{req.uuid}{path}")
            self.assertEqual((res.status_code, res.data["type"]), (404, "not_found"), path)
        self.assertEqual(self.client.get(f"{URL}/{req.uuid.__class__(int=1)}").status_code, 404)

    def test_detail_includes_days(self):
        req = make_request(self.agent, K.LEAVE, D(2026, 10, 20), status=S.APPROVED, leave_type=self.annual)
        AttendanceDay.objects.create(user=self.agent, date=D(2026, 10, 20), status="LEAVE",
                                     evaluated_at=NOW, request=req)
        self.authenticate_as(self.agent)
        res = self.client.get(f"{URL}/{req.uuid}")
        self.assertEqual(res.data["days"], [{"date": "2026-10-20", "status": "LEAVE"}])

    def test_patch_pending_and_after_decision_invalid_state(self):
        req = self.pending(self.agent)
        self.authenticate_as(self.agent)
        res = self.client.patch(f"{URL}/{req.uuid}", {"details": "new"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["details"], "new")
        req.status = S.APPROVED
        req.save()
        res = self.client.patch(f"{URL}/{req.uuid}", {"details": "again"}, format="json")
        self.assertEqual((res.status_code, res.data["type"]), (400, "invalid_state"))

    def test_patch_by_non_owner_403(self):
        req = self.pending(self.agent)
        self.authenticate_as(self.manager)
        res = self.client.patch(f"{URL}/{req.uuid}", {"details": "x"}, format="json")
        self.assertEqual((res.status_code, res.data["type"]), (403, "forbidden"))

    def test_approve_endpoint_returns_can_flags(self):
        req = self.pending(self.agent)
        self.authenticate_as(self.manager)
        res = self.client.post(f"{URL}/{req.uuid}/approve", {"note": "ok"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["status"], "APPROVED")
        self.assertEqual(res.data["decision_note"], "ok")
        self.assertEqual(res.data["decided_by"]["uuid"], str(self.manager.uuid))
        self.assertFalse(res.data["can"]["approve"])
        self.assertEqual(set(res.data["can"]), {"edit", "cancel", "request_cancellation", "approve",
                                                "reject", "revoke"})

    def test_approve_forbidden_for_agent_own(self):
        req = self.pending(self.agent)
        self.authenticate_as(self.agent)
        res = self.client.post(f"{URL}/{req.uuid}/approve")
        self.assertEqual((res.status_code, res.data["type"]), (403, "forbidden"))

    def test_reject_and_cancel(self):
        a, b = self.pending(self.agent), self.pending(self.agent, start=D(2026, 11, 9))
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.post(f"{URL}/{a.uuid}/reject", {"note": "no"}, format="json")
                         .data["status"], "REJECTED")
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.post(f"{URL}/{b.uuid}/cancel").data["status"], "CANCELLED")

    def test_revoke_without_note_400(self):
        req = make_request(self.agent, K.GENERAL, D(2026, 11, 2), status=S.APPROVED, details="x")
        self.authenticate_as(self.hr)
        res = self.client.post(f"{URL}/{req.uuid}/revoke", {}, format="json")
        self.assertEqual((res.status_code, res.data["type"]), (400, "validation"))
        res = self.client.post(f"{URL}/{req.uuid}/revoke", {"note": "mistake"}, format="json")
        self.assertEqual((res.status_code, res.data["status"]), (200, "REVOKED"))


class PeriodTests(RequestsApiBase):
    def test_period_endpoint(self):
        inside = self.pending(self.agent, start=D(2026, 10, 10))
        straddle = make_request(self.agent, K.LEAVE, D(2026, 9, 24), D(2026, 9, 26), status=S.PENDING,
                                leave_type=self.annual)
        self.pending(self.agent, start=D(2026, 9, 25))
        self.pending(self.agent, start=D(2026, 10, 26))
        self.pending(self.outsider, start=D(2026, 10, 10))
        self.authenticate_as(self.agent)
        res = self.client.get(f"{URL}/period", {"user": str(self.agent.uuid), "period": "2026-10"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r["uuid"] for r in res.data], [str(straddle.uuid), str(inside.uuid)])

    def test_period_forbidden_and_invalid(self):
        self.authenticate_as(self.agent)
        res = self.client.get(f"{URL}/period", {"user": str(self.outsider.uuid), "period": "2026-10"})
        self.assertEqual(res.status_code, 403)
        res = self.client.get(f"{URL}/period", {"period": "bad"})
        self.assertEqual(res.status_code, 400)
