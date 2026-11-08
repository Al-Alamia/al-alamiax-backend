from datetime import datetime


from apps.users.models import Project
from apps.users.tests.lead_fixtures import LeadPipelineTestCase

URL = "/api/users/leads/marketing-dashboard"


class MarketingDashboardTests(LeadPipelineTestCase):
    def at(self, y, m, d, h=12):
        return datetime(y, m, d, h)

    def lead(self, creator, when, **kw):
        return self.make_lead(creator, date=when, **kw)

    def get(self, user, **params):
        self.authenticate_as(user)
        return self.client.get(URL, params)

    def setUp(self):
        super().setUp()
        self.other = Project.objects.create(name="Other", color="#112233")
        self.lead(self.mk_agent, self.at(2026, 11, 3))
        self.lead(self.mk_agent, self.at(2026, 11, 3), status="subscriber")
        self.lead(self.mk_agent, self.at(2026, 11, 10), project=self.other)
        self.lead(self.mk_agent, self.at(2026, 11, 10), project=None)
        self.lead(self.mk_agent, self.at(2026, 10, 30))
        self.lead(self.sales_agent, self.at(2026, 11, 3))

    def test_month_mode(self):
        r = self.get(self.owner, mode="month", date="2026-11-15")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["range"], {"start": "2026-11-01", "end": "2026-11-30"})
        self.assertEqual(d["total"], 5)
        self.assertEqual(d["average"], "2.50")
        self.assertEqual(len(d["series"]), 30)
        series = {s["date"]: s["total"] for s in d["series"]}
        self.assertEqual(series["2026-11-03"], 3)
        self.assertEqual(series["2026-11-10"], 2)
        self.assertEqual(series["2026-11-04"], 0)
        projs = d["projects"]
        self.assertEqual(projs[0]["name"], "Test Project")
        self.assertEqual(projs[0]["total"], 3)
        none = [p for p in projs if p["uuid"] is None][0]
        self.assertEqual((none["name"], none["color"], none["total"]), ("—", "#64748b", 1))
        mk = [u for u in d["users"] if u["uuid"] == str(self.mk_agent.uuid)][0]
        self.assertEqual((mk["total"], mk["subscribers"]), (4, 1))
        self.assertEqual(mk["department"], "Marketing")
        self.assertEqual(mk["project"], "Test Project")

    def test_day_mode(self):
        d = self.get(self.owner, mode="day", date="2026-11-03").json()
        self.assertEqual(d["series"], [])
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["range"], {"start": "2026-11-03", "end": "2026-11-03"})

    def test_marketing_user_with_zero_leads_listed(self):
        d = self.get(self.owner, mode="day", date="2026-11-20").json()
        ids = [u["uuid"] for u in d["users"]]
        self.assertIn(str(self.mk_leader.uuid), ids)
        self.assertNotIn(str(self.sales_agent.uuid), ids)
        self.assertEqual(d["total"], 0)
        self.assertEqual(d["average"], "0.00")

    def test_agent_sees_only_self(self):
        d = self.get(self.sales_agent, mode="month", date="2026-11-15").json()
        self.assertEqual(d["total"], 1)
        self.assertEqual([u["uuid"] for u in d["users"]], [str(self.sales_agent.uuid)])

    def test_manager_sees_own_department(self):
        d = self.get(self.manager, mode="month", date="2026-11-15").json()
        self.assertEqual(d["total"], 1)
        ids = {u["uuid"] for u in d["users"]}
        self.assertIn(str(self.sales_agent.uuid), ids)
        self.assertNotIn(str(self.mk_agent.uuid), ids)

    def test_hr_sees_all(self):
        hr = self._user("hr1", "HR", self.sales)
        self.assertEqual(self.get(hr, date="2026-11-15").json()["total"], 5)

    def test_defaults_and_invalid(self):
        self.assertEqual(self.get(self.owner).status_code, 200)
        for params in ({"mode": "year"}, {"date": "nope"}):
            r = self.get(self.owner, **params)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["type"], "invalid")

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(URL).status_code, 401)
