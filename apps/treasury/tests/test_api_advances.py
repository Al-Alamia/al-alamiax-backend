import uuid
from datetime import date

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.periods import period_key_for
from apps.payroll_config.tests.factories import make_basic
from apps.treasury.models import Advance
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

B = "/api/treasury/advances"


class AdvanceApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.cur = period_key_for(date.today(), AttendanceSettings.get().period_start_day)
        make_basic(self.agent, date(2020, 1, 1), 3000)
        self.hr = User.objects.create_user(username="hr", password="x", email="hr@t.com", role=UserTypes.HR,
                                           project=self.project, department=self.department)
        self.manager = User.objects.create_user(username="mgr", password="x", email="m@t.com",
                                                role=UserTypes.MANAGER, project=self.project,
                                                department=self.department)
        other = Department.objects.create(name="Other")
        self.other = User.objects.create_user(username="oth", password="x", email="o@t.com",
                                              role=UserTypes.AGENT, project=self.project, department=other)
        make_basic(self.other, date(2020, 1, 1), 2000)
        self.agent2 = User.objects.create_user(username="ag2", password="x", email="a2@t.com",
                                               role=UserTypes.AGENT, project=self.project,
                                               department=self.department)

    def post(self, **kw):
        body = {"amount": "1000", "installments": 2, "start_period": self.cur, "reason": "r"}
        body.update(kw)
        return self.client.post(B, body, format="json")

    def test_post_self_and_shape(self):
        self.authenticate_as(self.agent)
        r = self.post()
        self.assertEqual(r.status_code, 201, r.data)
        d = r.data
        self.assertEqual(d["user"]["uuid"], str(self.agent.pk))
        self.assertEqual(d["requested_by"]["uuid"], str(self.agent.pk))
        self.assertEqual((d["amount"], d["status"], d["installments"]), ("1000.00", "pending", 2))
        self.assertEqual(d["schedule"], [])
        self.assertFalse(d["can_decide"])
        self.assertIsNone(d["decided_by"])
        self.assertEqual(self.post().data["type"], "pending_exists")

    def test_post_on_behalf_and_forbidden(self):
        self.authenticate_as(self.hr)
        r = self.post(user=str(self.agent.pk))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["requested_by"]["uuid"], str(self.hr.pk))
        self.assertTrue(r.data["can_decide"])
        self.authenticate_as(self.agent2)
        r = self.post(user=str(self.agent.pk))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.post(user="nope").status_code, 400)
        self.assertEqual(self.post(user=str(uuid.uuid4())).status_code, 400)

    def test_post_error_types(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.post(amount="3000.01").data["type"], "over_limit")
        self.authenticate_as(self.agent2)
        self.assertEqual(self.post().data["type"], "no_basic")

    def test_integrity_error_maps_to_pending_exists(self):
        from unittest import mock
        from django.db import IntegrityError
        self.authenticate_as(self.agent)
        with mock.patch("apps.treasury.views.advances.advances.request_advance", side_effect=IntegrityError):
            r = self.post()
        self.assertEqual((r.status_code, r.data["type"]), (400, "pending_exists"))

    def test_mine_and_list_scope(self):
        from apps.treasury.services import advances as svc
        a1 = svc.request_advance(self.agent, self.agent, "100", 1, self.cur)
        svc.request_advance(self.other, self.other, "100", 1, self.cur)
        self.authenticate_as(self.agent)
        r = self.client.get(B + "/mine")
        self.assertEqual([x["id"] for x in r.data], [str(a1.pk)])
        self.assertEqual(self.client.get(B).status_code, 403)
        self.authenticate_as(self.manager)
        r = self.client.get(B)
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(r.data["results"][0]["id"], str(a1.pk))
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.get(B).data["count"], 2)

    def test_filters(self):
        from apps.treasury.services import advances as svc
        a1 = svc.request_advance(self.agent, self.agent, "100", 2, self.cur)
        svc.approve_advance(self.hr, a1)
        nxt = svc.period_keys(self.cur, 2)[1]
        a2 = svc.request_advance(self.other, self.other, "100", 1, nxt)
        self.authenticate_as(self.hr)
        ids = lambda q: {x["id"] for x in self.client.get(B + q).data["results"]}
        self.assertEqual(ids("?status=approved"), {str(a1.pk)})
        self.assertEqual(ids("?status=pending"), {str(a2.pk)})
        self.assertEqual(ids(f"?user={self.other.pk}"), {str(a2.pk)})
        self.assertEqual(ids(f"?period={nxt}"), {str(a1.pk), str(a2.pk)})
        self.assertEqual(ids(f"?period={self.cur}"), {str(a1.pk)})
        self.assertEqual(self.client.get(B + "?period=bad").status_code, 400)
        self.assertEqual(self.client.get(B + "?user=zzz").status_code, 400)

    def test_limit(self):
        self.authenticate_as(self.agent)
        r = self.client.get(B + f"/limit?start_period={self.cur}")
        self.assertEqual(r.data, {"basic": "3000.00", "max": "3000.00"})
        self.assertEqual(self.client.get(B + f"/limit?user={self.other.pk}&start_period={self.cur}")
                         .status_code, 403)
        self.assertEqual(self.client.get(B + "/limit").status_code, 400)
        self.assertEqual(self.client.get(B + "/limit?start_period=2026-13").status_code, 400)
        self.authenticate_as(self.hr)
        r = self.client.get(B + f"/limit?user={self.agent2.pk}&start_period={self.cur}")
        self.assertEqual(r.data, {"basic": None, "max": None})

    def test_decisions(self):
        from apps.treasury.services import advances as svc
        a = svc.request_advance(self.agent, self.agent, "100", 2, self.cur)
        url = lambda act, pk=None: f"{B}/{pk or a.pk}/{act}"
        self.authenticate_as(self.agent)
        self.assertFalse(self.client.get(B + "/mine").data[0]["can_decide"])
        self.assertEqual(self.client.post(url("approve"), {}, format="json").status_code, 403)
        self.authenticate_as(self.hr)
        self.assertEqual(self.client.post(url("approve", uuid.uuid4()), {}, format="json").status_code, 404)
        r = self.client.post(url("reject"), {}, format="json")
        self.assertEqual(r.data["type"], "invalid")
        r = self.client.post(url("approve"), {"note": "ok"}, format="json")
        self.assertEqual((r.status_code, r.data["status"], r.data["decision_note"]), (200, "approved", "ok"))
        self.assertEqual(len(r.data["schedule"]), 2)
        self.assertEqual(r.data["schedule"][0], {"period": self.cur, "amount": "50.00"})
        self.assertEqual(r.data["decided_by"]["uuid"], str(self.hr.pk))
        self.assertTrue(r.data["can_decide"])
        r = self.client.post(url("cancel"), {"reason": "oops"}, format="json")
        self.assertEqual((r.data["status"], r.data["cancel_reason"]), ("cancelled", "oops"))
        self.assertFalse(r.data["can_decide"])

    def test_reject_and_withdraw(self):
        from apps.treasury.services import advances as svc
        a = svc.request_advance(self.agent, self.agent, "100", 1, self.cur)
        self.authenticate_as(self.agent)
        r = self.client.post(f"{B}/{a.pk}/withdraw", {}, format="json")
        self.assertEqual(r.data["status"], "withdrawn")
        b = svc.request_advance(self.agent, self.agent, "100", 1, self.cur)
        self.authenticate_as(self.manager)
        r = self.client.post(f"{B}/{b.pk}/reject", {"note": "no"}, format="json")
        self.assertEqual((r.data["status"], r.data["decision_note"]), ("rejected", "no"))
        self.assertEqual(Advance.objects.get(pk=b.pk).status, "rejected")
