from datetime import date, timedelta

from apps.attendance.models import AttendanceSettings, PeriodClose
from apps.attendance.services.periods import period_key_for, period_range
from apps.payroll_config.tests.factories import make_basic
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

BASE = "/api/monthly-basic/"


def keys():
    sd = AttendanceSettings.get().period_start_day
    cur = period_key_for(date.today(), sd)
    prev = period_key_for(period_range(cur, sd)[0] - timedelta(days=1), sd)
    return prev, cur  # prev has ended, cur is current (not ended)


class ApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.prev, self.cur = keys()
        self.month = date(int(self.prev[:4]), int(self.prev[5:]), 1)
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR, department=self.department)
        self.mgr = User.objects.create_user(username="mg", password="x", role=UserTypes.MANAGER, department=self.department)
        self.other_dept = Department.objects.create(name="Other")
        self.other = User.objects.create_user(username="zed", password="x", role=UserTypes.AGENT,
                                              department=self.other_dept, first_name="Zed")
        self.nosal = User.objects.create_user(username="nosal", password="x", role=UserTypes.AGENT, department=self.department)
        make_basic(self.agent, date(2020, 1, 1), 3000)
        make_basic(self.other, date(2020, 1, 1), 1500)
        self.url = f"{BASE}users/{self.agent.uuid}"

    def get(self, user, path="", **params):
        self.authenticate_as(user)
        params.setdefault("period", self.prev)
        return self.client.get(BASE + path, params)

    def post(self, user, path, **body):
        self.authenticate_as(user)
        body.setdefault("period", self.prev)
        return self.client.post(BASE + path, body, format="json")

    def give_all(self):
        for u in (self.agent, self.other):
            self.assertEqual(self.post(self.hr, f"users/{u.uuid}/give").status_code, 200)

    def test_list_hr(self):
        r = self.get(self.hr)
        self.assertEqual(r.status_code, 200)
        d = r.data
        self.assertEqual([x["user"]["username"] for x in d["results"]], ["agent", "zed"])
        self.assertEqual([m["name"] for m in d["missing_salary"]].count("nosal"), 1)
        self.assertEqual(d["totals"]["total"], 2)
        self.assertEqual(d["totals"]["given"], 0)
        self.assertEqual(d["results"][0]["basic"], "3000.00")
        self.assertEqual(d["totals"]["basic"], "4500.00")
        self.assertEqual(d["period"], self.prev)
        date.fromisoformat(d["start"]); date.fromisoformat(d["end"])
        self.assertEqual(d["results"][0]["user"]["department"]["name"], "Test Department")

    def test_list_filters(self):
        d = self.get(self.hr, department=str(self.other_dept.uuid)).data
        self.assertEqual([x["user"]["username"] for x in d["results"]], ["zed"])
        self.assertEqual(d["totals"]["total"], 1)
        self.assertEqual(d["missing_salary"], [])
        d = self.get(self.hr, search="age").data
        self.assertEqual(d["totals"]["total"], 1)
        self.post(self.hr, f"users/{self.agent.uuid}/give")
        d = self.get(self.hr, status="given").data
        self.assertEqual([x["user"]["username"] for x in d["results"]], ["agent"])
        self.assertEqual((d["totals"]["given"], d["totals"]["total"]), (1, 1))
        d = self.get(self.hr, status="draft").data
        self.assertEqual([x["user"]["username"] for x in d["results"]], ["zed"])
        self.assertEqual(self.get(self.hr, status="x").status_code, 400)

    def test_list_manager_scope_and_agent_403(self):
        d = self.get(self.mgr).data
        self.assertEqual([x["user"]["username"] for x in d["results"]], ["agent"])
        self.assertEqual(self.get(self.agent).status_code, 403)

    def test_list_flags(self):
        d = self.get(self.hr).data
        self.assertTrue(d["can_close"]); self.assertFalse(d["can_reopen"]); self.assertTrue(d["can_give"])
        self.assertFalse(self.get(self.hr, period=self.cur).data["can_close"])
        self.give_all()
        self.assertEqual(self.post(self.hr, "close").status_code, 200)
        d = self.get(self.superuser).data
        self.assertEqual(d["closed"]["closed_by"]["uuid"], str(self.hr.uuid))
        self.assertTrue(d["can_reopen"]); self.assertFalse(d["can_close"]); self.assertFalse(d["can_give"])
        self.assertFalse(d["results"][0]["can_edit"])

    def test_detail_and_patch(self):
        d = self.get(self.hr, f"users/{self.agent.uuid}").data
        for k in ("inputs", "breakdown", "can_edit", "can_give", "user", "status", "period_closed"):
            self.assertIn(k, d)
        self.assertEqual(d["breakdown"]["net"], "3000.00")
        self.authenticate_as(self.hr)
        r = self.client.patch(f"{self.url}?period={self.prev}", {"kpi": "100"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["breakdown"]["kpi"], "100.00")
        self.assertEqual(r.data["inputs"]["kpi"], "100.00")
        r = self.client.patch(f"{self.url}?period={self.prev}", {"kpi": "-5"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_detail_not_included_is_read_only(self):
        r = self.get(self.hr, f"users/{self.nosal.uuid}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_edit"])
        self.assertFalse(r.data["can_give"])

    def test_manager_other_department_404(self):
        for u in (self.other, self.superuser):
            url = f"users/{u.uuid}"
            self.assertEqual(self.get(self.mgr, url).status_code, 404)
            self.authenticate_as(self.mgr)
            self.assertEqual(self.client.patch(f"{BASE}{url}?period={self.prev}", {"kpi": "1"}, format="json").status_code, 404)
            self.assertEqual(self.post(self.mgr, url + "/give").status_code, 404)

    def test_agent_own_given_only(self):
        self.assertEqual(self.get(self.agent, f"users/{self.agent.uuid}").status_code, 404)
        self.post(self.hr, f"users/{self.agent.uuid}/give")
        r = self.get(self.agent, f"users/{self.agent.uuid}")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_edit"]); self.assertFalse(r.data["can_give"])

    def test_give_ungive_close_reopen_endpoints(self):
        self.assertEqual(self.post(self.hr, "close").data["type"], "not_all_given")
        self.assertEqual(self.post(self.hr, f"users/{self.agent.uuid}/give", period=self.cur).data["type"], "period_open")
        self.give_all()
        r = self.post(self.hr, f"users/{self.agent.uuid}/give")
        self.assertEqual((r.status_code, r.data["type"]), (400, "already_given"))
        self.assertEqual(self.post(self.mgr, "close").status_code, 403)
        self.assertEqual(self.post(self.hr, "close").status_code, 200)
        self.assertTrue(PeriodClose.objects.filter(period=self.prev).exists())
        self.assertEqual(self.post(self.hr, f"users/{self.agent.uuid}/ungive").data["type"], "period_closed")
        r = self.post(self.hr, "reopen", reason="x")
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        self.assertEqual(self.post(self.superuser, "reopen", reason="").data["type"], "invalid")
        self.assertEqual(self.post(self.superuser, "reopen", reason="fix").status_code, 200)
        r = self.post(self.hr, f"users/{self.agent.uuid}/ungive")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "draft")

    def test_bad_period(self):
        r = self.get(self.hr, period="2026-13")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.get(self.hr, period="2999-01")
        self.assertEqual((r.status_code, r.data["type"]), (400, "future_period"))
        self.assertEqual(self.get(self.hr, "users/00000000-0000-0000-0000-000000000000").status_code, 404)
        self.assertEqual(self.get(self.hr, period="").status_code, 200)
