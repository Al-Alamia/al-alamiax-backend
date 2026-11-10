import datetime
from decimal import Decimal

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.periods import period_key_for, period_range
from apps.mcp_server.registry import call_tool, load_tools
from apps.mcp_server.tests.base import McpTestCase
from apps.payroll_config.tests.factories import make_basic
from apps.penalties.tests.factories import make_penalty
from apps.salaries.models import Salary
from apps.treasury.models import Advance


class PayrollToolsTests(McpTestCase):
    def setUp(self):
        super().setUp()
        load_tools()
        sd = AttendanceSettings.get().period_start_day
        self.key = period_key_for(datetime.date.today(), sd)
        self.start = period_range(self.key, sd)[0]
        for u in (self.agent, self.other_agent, self.owner, self.manager):
            make_basic(u, datetime.date(2020, 1, 1), 3000)

    def call(self, user, name, args=None):
        return call_tool(user, name, args or {})

    def test_get_salary_happy_and_read_only(self):
        res = self.call(self.manager, "get_salary", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(res["isError"])
        d = res["structuredContent"]
        self.assertEqual(d["period"], self.key)
        self.assertEqual(d["status"], "draft")
        self.assertIn("parts", d)
        self.assertEqual(Salary.objects.count(), 0)

    def test_get_salary_manager_other_department_not_found(self):
        res = self.call(self.manager, "get_salary", {"user_uuid": str(self.other_agent.pk)})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    def test_hr_cannot_see_owner_salary(self):
        res = self.call(self.hr, "get_salary", {"user_uuid": str(self.owner.pk)})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        ok = self.call(self.owner, "get_salary", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(ok["isError"])

    def test_list_salaries_scope(self):
        res = self.call(self.manager, "list_salaries", {})
        self.assertFalse(res["isError"])
        names = {r["user"]["username"] for r in res["structuredContent"]["items"]}
        self.assertIn(self.agent.username, names)
        self.assertNotIn(self.other_agent.username, names)
        hr = self.call(self.hr, "list_salaries", {})
        hr_names = {r["user"]["username"] for r in hr["structuredContent"]["items"]}
        self.assertIn(self.other_agent.username, hr_names)
        self.assertNotIn(self.owner.username, hr_names)
        self.assertEqual(Salary.objects.count(), 0)

    def test_list_salaries_limit(self):
        res = self.call(self.hr, "list_salaries", {"limit": 1})
        self.assertEqual(res["structuredContent"]["count"], 1)
        self.assertTrue(res["structuredContent"]["truncated"])

    def test_get_monthly_basic(self):
        res = self.call(self.manager, "get_monthly_basic", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(res["isError"])
        self.assertIn("breakdown", res["structuredContent"])
        for caller, target in ((self.manager, self.other_agent), (self.hr, self.owner)):
            bad = self.call(caller, "get_monthly_basic", {"user_uuid": str(target.pk)})
            self.assertTrue(bad["isError"])
            self.assertEqual(bad["structuredContent"]["error"], "not_found")

    def test_list_penalties(self):
        mine = make_penalty(self.agent, self.manager, date=self.start)
        make_penalty(self.other_agent, self.hr, date=self.start)
        voided = make_penalty(self.agent, self.manager, date=self.start)
        voided.voided_at = datetime.datetime(2026, 1, 1)
        voided.voided_by = self.manager
        voided.save()
        res = self.call(self.manager, "list_penalties", {"period": self.key})
        items = res["structuredContent"]["items"]
        self.assertEqual([i["uuid"] for i in items], [str(mine.uuid)])
        inc = self.call(self.manager, "list_penalties", {"include_voided": True})
        self.assertEqual(inc["structuredContent"]["count"], 2)
        bad = self.call(self.manager, "list_penalties", {"user_uuid": str(self.other_agent.pk)})
        self.assertEqual(bad["structuredContent"]["error"], "not_found")

    def test_list_penalties_hr_cannot_see_owner(self):
        make_penalty(self.owner, self.owner)
        res = self.call(self.hr, "list_penalties", {})
        self.assertEqual(res["structuredContent"]["count"], 0)
        bad = self.call(self.hr, "list_penalties", {"user_uuid": str(self.owner.pk)})
        self.assertEqual(bad["structuredContent"]["error"], "not_found")

    def test_list_advances(self):
        a = Advance.objects.create(user=self.agent, amount=Decimal("500"), installments=2,
                                   start_period=self.key)
        Advance.objects.create(user=self.other_agent, amount=Decimal("100"), installments=1,
                               start_period=self.key)
        res = self.call(self.manager, "list_advances", {})
        self.assertEqual([i["id"] for i in res["structuredContent"]["items"]], [str(a.pk)])
        self.assertEqual(res["structuredContent"]["items"][0]["amount"], "500.00")
        f = self.call(self.manager, "list_advances", {"status": "approved"})
        self.assertEqual(f["structuredContent"]["count"], 0)
        bad = self.call(self.manager, "list_advances", {"user_uuid": str(self.other_agent.pk)})
        self.assertEqual(bad["structuredContent"]["error"], "not_found")
        hr = self.call(self.hr, "list_advances", {})
        self.assertEqual(hr["structuredContent"]["count"], 2)

    def test_agent_does_not_see_tools(self):
        from apps.mcp_server.registry import visible_tools
        names = {t.name for t in visible_tools(self.agent)}
        self.assertNotIn("get_salary", names)
