from decimal import Decimal

from apps.payroll_config.tests.factories import make_basic
from apps.salaries import services
from apps.salaries.tests.factories import KEY, MONTH, give_basic, make_lead_on, window
from apps.subscriptions.tests.factories import marketing_dept
from apps.teams.tests.factories import make_plan, make_team, make_version
from apps.teams.types import PlanKind
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

UNIT10 = [{"min_value": 1, "kind": "unit", "value": 10}]
BASE = "/api/salaries/"


class SalariesApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.start, self.end = window()
        self.M = marketing_dept()
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR, department=self.M)
        self.a1 = self.mk("alpha")
        self.a2 = self.mk("beta")
        give_basic(self.a1, 2900)
        make_version(make_plan(PlanKind.PERSONAL, department=self.M), MONTH, UNIT10)
        make_lead_on(self.a1, self.start)

    def mk(self, name):
        u = User.objects.create_user(username=name, password="x", role=UserTypes.AGENT, department=self.M)
        make_basic(u, MONTH, 3000)
        return u

    def give(self, user):
        services.give(self.hr, user, KEY, today=self.end)

    def get(self, path="", **params):
        return self.client.get(BASE + path, {"period": KEY, **params})

    def test_list_shape_and_totals(self):
        self.authenticate_as(self.hr)
        r = self.get()
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(set(d), {"period", "start", "end", "closed", "can_give_all", "totals",
                                  "projects", "results"})
        self.assertTrue(d["can_give_all"])
        self.assertEqual(d["totals"]["count"], 2)
        rows = {x["user"]["username"]: x for x in d["results"]}
        self.assertEqual(rows["beta"]["basic_net"], None)
        self.assertEqual(rows["beta"]["total"], None)
        self.assertEqual(rows["beta"]["error_types"], ["basic_not_given"])
        self.assertEqual(rows["alpha"]["basic_net"], "2900.00")
        self.assertEqual(rows["alpha"]["commission"], "10.00")
        self.assertEqual(rows["alpha"]["total"], "2910.00")
        self.assertEqual(d["totals"]["total"], "2910.00")
        self.assertEqual(d["totals"]["given"], 0)
        self.assertEqual(len(d["projects"]), 1)
        self.assertIsNone(d["projects"][0]["project"])

    def test_list_filters(self):
        self.give(self.a1)
        self.authenticate_as(self.hr)
        self.assertEqual([x["user"]["username"] for x in self.get(status="given").json()["results"]],
                         ["alpha"])
        self.assertEqual([x["user"]["username"] for x in self.get(status="draft").json()["results"]],
                         ["beta"])
        other = Department.objects.create(name="Other")
        self.a2.department = other
        self.a2.save()
        res = self.get(department=str(other.uuid)).json()["results"]
        self.assertEqual([x["user"]["username"] for x in res], ["beta"])
        self.assertEqual(len(self.get(search="alp").json()["results"]), 1)
        r = self.get(status="bad")
        self.assertEqual((r.status_code, r.json()["type"]), (400, "invalid"))

    def test_list_forbidden_for_agent(self):
        self.authenticate_as(self.a1)
        r = self.get()
        self.assertEqual((r.status_code, r.json()["type"]), (403, "forbidden"))

    def test_detail_and_self_view(self):
        self.authenticate_as(self.a1)
        self.assertEqual(self.get(f"users/{self.a1.uuid}").status_code, 404)
        self.give(self.a1)
        r = self.get(f"users/{self.a1.uuid}")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["status"], "given")
        self.assertFalse(d["can_edit"])
        self.assertEqual(d["total"], "2910.00")
        self.authenticate_as(self.a2)
        self.assertEqual(self.get(f"users/{self.a1.uuid}").status_code, 404)

    def test_detail_hr_shape(self):
        self.authenticate_as(self.hr)
        d = self.get(f"users/{self.a1.uuid}").json()
        self.assertEqual(set(d), {"period", "start", "end", "period_closed", "user", "status", "given_by",
                                  "given_at", "basic", "parts", "commission", "total", "errors",
                                  "can_edit", "can_give", "can_ungive"})
        self.assertTrue(d["can_edit"])
        self.assertTrue(d["can_give"])
        self.assertFalse(d["can_ungive"])
        d2 = self.get(f"users/{self.a2.uuid}").json()
        self.assertTrue(d2["can_edit"])
        self.assertFalse(d2["can_give"])

    def test_override_put_delete_with_colon_key(self):
        leader = self.mk("ld")
        give_basic(leader, 1000)
        team = make_team(self.M, leader=leader, agents=[self.a1, self.a2])
        make_version(make_plan(PlanKind.TEAM, team=team, metric="lead_count"), MONTH,
                     [{"min_value": 1, "kind": "flat", "value": 500}])
        key = f"team:{team.uuid}:lead_count"
        self.authenticate_as(self.hr)
        url = f"{BASE}users/{leader.uuid}/overrides/{key}"
        r = self.client.put(url, {"period": KEY, "value": "700", "reason": "manual"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        part = next(p for p in r.json()["parts"] if p["key"] == key)
        self.assertEqual(part["amount"], "700.00")
        r = self.client.delete(url + f"?period={KEY}")
        self.assertEqual(r.status_code, 200, r.content)
        part = next(p for p in r.json()["parts"] if p["key"] == key)
        self.assertEqual(part["amount"], part["computed"])
        self.assertIsNone(part["override"])
        bad = self.client.put(url, {"period": KEY, "value": "-1", "reason": "x"}, format="json")
        self.assertEqual((bad.status_code, bad.json()["type"]), (400, "invalid"))

    def test_give_ungive_endpoints(self):
        self.authenticate_as(self.hr)
        r = self.client.post(f"{BASE}users/{self.a2.uuid}/give", {"period": KEY}, format="json")
        self.assertEqual((r.status_code, r.json()["type"]), (400, "basic_not_given"))
        r = self.client.post(f"{BASE}users/{self.a1.uuid}/give", {"period": KEY}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "given")
        self.assertTrue(r.json()["can_ungive"])
        r = self.client.post(f"{BASE}users/{self.a1.uuid}/ungive", {"period": KEY}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "draft")

    def test_give_all_endpoint(self):
        self.authenticate_as(self.hr)
        r = self.client.post(BASE + "give-all", {"period": KEY}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertEqual(set(d), {"given", "skipped"})
        self.assertEqual(d["given"], 1)
        self.authenticate_as(self.a1)
        r = self.client.post(BASE + "give-all", {"period": KEY}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_invalid_and_future_period(self):
        self.authenticate_as(self.hr)
        r = self.client.get(BASE, {"period": "nope"})
        self.assertEqual((r.status_code, r.json()["type"]), (400, "invalid"))
        r = self.client.get(BASE, {"period": "2999-01"})
        self.assertEqual((r.status_code, r.json()["type"]), (400, "future_period"))

    def test_mine_and_history(self):
        self.give(self.a1)
        self.authenticate_as(self.a1)
        d = self.client.get(BASE + "mine").json()
        self.assertEqual(len(d["results"]), 1)
        row = d["results"][0]
        self.assertEqual(set(row), {"period", "basic_net", "commission", "total", "given_at"})
        self.assertEqual(row["total"], "2910.00")
        self.authenticate_as(self.a2)
        self.assertEqual(self.client.get(BASE + "mine").json(), {"results": []})
        self.assertEqual(self.client.get(f"{BASE}users/{self.a1.uuid}/history").status_code, 404)
        self.authenticate_as(self.hr)
        r = self.client.get(f"{BASE}users/{self.a1.uuid}/history")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["results"]), 1)
        self.authenticate_as(self.a1)
        self.assertEqual(self.client.get(f"{BASE}users/{self.a1.uuid}/history").status_code, 200)
