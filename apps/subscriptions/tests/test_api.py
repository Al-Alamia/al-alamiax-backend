import datetime as dt

from apps.subscriptions.models import Subscription
from apps.subscriptions.tests.factories import (
    assign, make_lead, make_payment, make_subscription, marketing_dept, sales_dept,
)
from apps.teams.models import Team
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

BASE = "/api/subscriptions/"


def mk(username, role, dept):
    return User.objects.create_user(
        username=username, password="x", email=f"{username}@t.com", role=role,
        project=None, department=dept,
    )


class SubscriptionApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        sales, mkt = sales_dept(), marketing_dept()
        self.manager = mk("a_manager", UserTypes.MANAGER, sales)
        self.leader = mk("a_leader", UserTypes.AGENT, sales)
        self.a = mk("a_a", UserTypes.AGENT, sales)
        self.b = mk("a_b", UserTypes.AGENT, sales)
        self.m = mk("a_m", UserTypes.AGENT, mkt)
        self.hr = mk("a_hr", UserTypes.HR, self.department)
        team = Team.objects.create(name="T", department=sales, leader=self.leader)
        team.agents.add(self.a)
        self.l1 = make_lead(self.m)
        assign(self.l1, self.a, "sales")
        self.today = dt.date.today()
        self.body = {
            "kind": "new", "plan_name": "Gold", "market": "saudi", "currency": "SAR",
            "total_amount": "1000", "start_date": self.today.isoformat(),
            "end_date": (self.today + dt.timedelta(days=30)).isoformat(),
        }

    def as_(self, user):
        self.client.force_authenticate(user)
        return self.client

    def test_full_flow(self):
        c = self.as_(self.a)
        r = c.get(f"{BASE}leads/{self.l1.uuid}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["can"]["create"])
        self.assertEqual(r.data["sellers"], [])
        r = c.post(f"{BASE}leads/{self.l1.uuid}", self.body, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        sub = r.data["uuid"]
        self.assertEqual(r.data["seller"]["uuid"], str(self.a.pk))
        r = c.post(f"{BASE}{sub}/payments", {
            "amount": "600", "paid_on": self.today.isoformat(), "method": "cash"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data["locked"])
        self.assertTrue(r.data["can"]["edit"])
        r = c.get(f"{BASE}leads/{self.l1.uuid}")
        s = r.data["results"][0]
        self.assertEqual(s["paid_amount"], "600.00")
        self.assertEqual(s["remaining_amount"], "400.00")
        self.assertEqual(len(s["payments"]), 1)
        self.assertEqual(s["status"], "active")

    def test_marketer_denied_and_other_agent_404(self):
        self.assertEqual(self.as_(self.m).get(f"{BASE}leads/{self.l1.uuid}").status_code, 403)
        self.assertEqual(self.as_(self.b).get(f"{BASE}leads/{self.l1.uuid}").status_code, 404)

    def test_leader_choose_seller(self):
        r = self.as_(self.leader).get(f"{BASE}leads/{self.l1.uuid}")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["can"]["choose_seller"])
        self.assertEqual([s["uuid"] for s in r.data["sellers"]], [str(self.a.pk)])

    def test_hidden_lead_visible_to_manager_only(self):
        self.l1.is_hidden = True
        self.l1.save()
        self.assertEqual(self.as_(self.manager).get(f"{BASE}leads/{self.l1.uuid}").status_code, 200)
        self.assertEqual(self.as_(self.a).get(f"{BASE}leads/{self.l1.uuid}").status_code, 404)

    def test_error_cases(self):
        sub = make_subscription(self.l1, self.a)
        make_payment(sub, "600", self.today)
        c = self.as_(self.leader)
        r = c.patch(f"{BASE}{sub.uuid}", {"total_amount": "500"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "overpaid"))
        r = c.post(f"{BASE}{sub.uuid}/cancel", {}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = c.delete(f"{BASE}{sub.uuid}")
        self.assertEqual((r.status_code, r.data["type"]), (400, "has_payments"))
        r = c.post(f"{BASE}{sub.uuid}/cancel", {"reason": "x"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.data["cancelled_at"])

    def test_payment_update_delete(self):
        sub = make_subscription(self.l1, self.a)
        p = make_payment(sub, "100", self.today, recorded_by=self.a)
        c = self.as_(self.a)
        r = c.patch(f"{BASE}payments/{p.uuid}", {"amount": "200"}, format="json")
        self.assertEqual((r.status_code, r.data["amount"]), (200, "200.00"))
        self.assertEqual(c.delete(f"{BASE}payments/{p.uuid}").status_code, 204)
        self.assertEqual(self.as_(self.b).delete(f"{BASE}payments/{p.uuid}").status_code, 404)

    def test_update_and_delete_subscription(self):
        sub = make_subscription(self.l1, self.a)
        c = self.as_(self.manager)
        r = c.patch(f"{BASE}{sub.uuid}", {"plan_name": "Silver"}, format="json")
        self.assertEqual((r.status_code, r.data["plan_name"]), (200, "Silver"))
        self.assertEqual(c.delete(f"{BASE}{sub.uuid}").status_code, 204)
        self.assertFalse(Subscription.objects.filter(pk=sub.pk).exists())

    def test_list_filters_and_summary(self):
        make_subscription(self.l1, self.a, kind="renewal")
        make_subscription(self.l1, self.a, kind="new")
        c = self.as_(self.manager)
        r = c.get(BASE)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["summary"]["count"], 2)
        self.assertNotIn("payments", r.data["results"][0])
        self.assertIn("can", r.data["results"][0])
        r = c.get(BASE, {"kind": "renewal"})
        self.assertEqual(len(r.data["results"]), 1)
        self.assertEqual(r.data["summary"]["renewal_count"], 1)
        self.assertEqual(r.data["summary"]["new_count"], 0)

    def test_list_bad_range_and_denied(self):
        r = self.as_(self.manager).get(BASE, {"from": "2026-11-10", "to": "2026-11-01"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.as_(self.manager).get(BASE, {"from": "nope"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.as_(self.hr).get(BASE).status_code, 403)

    def test_list_status_expired_and_search(self):
        past = self.today - dt.timedelta(days=10)
        make_subscription(self.l1, self.a, start_date=past - dt.timedelta(days=5), end_date=past)
        make_subscription(self.l1, self.a, plan_name="Platinum")
        c = self.as_(self.manager)
        r = c.get(BASE, {"status": "expired"})
        self.assertEqual(len(r.data["results"]), 1)
        self.assertEqual(r.data["results"][0]["status"], "expired")
        r = c.get(BASE, {"status": "active", "search": "plat"})
        self.assertEqual(len(r.data["results"]), 1)
        self.assertEqual(c.get(BASE, {"status": "bogus"}).status_code, 400)
