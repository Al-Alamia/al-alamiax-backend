from datetime import date, timedelta

from apps.mcp_server.registry import call_tool, load_tools
from apps.mcp_server.tests.base import McpTestCase
from apps.subscriptions.tests.factories import assign, make_lead, make_payment, make_subscription
from apps.users.models import Department, LeadUpdate
from apps.users.types import DepartmentCodes


class LeadToolsTests(McpTestCase):
    def setUp(self):
        super().setUp()
        load_tools()
        Department.objects.filter(pk=self.department.pk).update(code=DepartmentCodes.SALES)
        for u in (self.agent, self.manager, self.leader, self.owner):
            u.refresh_from_db()
        self.lead = make_lead(self.other_agent, name="Alpha Lead", project=self.project)
        assign(self.lead, self.agent, by=self.manager)
        self.hidden_from_agent = make_lead(self.other_agent, name="Beta Lead")
        assign(self.hidden_from_agent, self.leader, by=self.manager)

    def call(self, user, name, args=None):
        return call_tool(user, name, args or {})

    def test_search_leads_agent_sees_only_assigned(self):
        res = self.call(self.agent, "search_leads", {})
        self.assertFalse(res["isError"])
        items = res["structuredContent"]["items"]
        self.assertEqual([i["uuid"] for i in items], [str(self.lead.pk)])
        self.assertEqual(items[0]["phone"], self.lead.phone)
        self.assertEqual(items[0]["sales_agent"]["uuid"], str(self.agent.pk))

    def test_search_leads_manager_filters(self):
        res = self.call(self.manager, "search_leads", {"query": "alpha"})
        self.assertEqual(len(res["structuredContent"]["items"]), 1)
        res = self.call(self.manager, "search_leads", {"assignee_uuid": str(self.leader.pk)})
        self.assertEqual([i["name"] for i in res["structuredContent"]["items"]], ["Beta Lead"])
        res = self.call(self.manager, "search_leads", {"project": self.project.name})
        self.assertEqual([i["name"] for i in res["structuredContent"]["items"]], ["Alpha Lead"])
        res = self.call(self.manager, "search_leads", {"status": "interested"})
        self.assertEqual(res["structuredContent"]["items"], [])
        tomorrow = (date.today() + timedelta(days=2)).isoformat()
        res = self.call(self.manager, "search_leads", {"created_from": tomorrow})
        self.assertEqual(res["structuredContent"]["items"], [])

    def test_search_leads_other_department_forbidden(self):
        res = self.call(self.hr, "search_leads", {})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "forbidden")

    def test_get_lead_hides_invisible_agent_refs(self):
        assign(self.lead, self.other_agent, kind="cs", by=self.manager)
        LeadUpdate.objects.create(lead=self.lead, by=self.other_agent, type="note", note="x")
        res = self.call(self.manager, "get_lead", {"lead_uuid": str(self.lead.pk)})
        self.assertFalse(res["isError"])
        data = res["structuredContent"]
        self.assertIsNone(data["cs_agent"])
        self.assertEqual(data["sales_agent"]["uuid"], str(self.agent.pk))
        by_kind = {a["kind"]: a["agent"] for a in data["assignments"]}
        self.assertIsNone(by_kind["cs"])
        self.assertIsNotNone(by_kind["sales"])
        self.assertIsNone(data["created_by"])
        self.assertIsNone(data["history"][0]["by"])

    def test_subscription_seller_hidden_when_invisible(self):
        make_subscription(self.lead, self.other_agent)
        res = self.call(self.manager, "list_subscriptions", {})
        self.assertFalse(res["isError"])
        items = res["structuredContent"]["items"]
        self.assertTrue(items)
        self.assertIsNone(items[0]["seller"])

    def test_get_lead_detail_and_not_found(self):
        LeadUpdate.objects.create(lead=self.lead, by=self.manager, type="note", note="hi")
        res = self.call(self.agent, "get_lead", {"lead_uuid": str(self.lead.pk)})
        self.assertFalse(res["isError"])
        data = res["structuredContent"]
        self.assertEqual(data["assignments"][0]["agent"]["uuid"], str(self.agent.pk))
        self.assertEqual(data["history"][0]["note"], "hi")
        self.assertEqual(data["subscriptions"], [])
        res = self.call(self.agent, "get_lead", {"lead_uuid": str(self.hidden_from_agent.pk)})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    def test_get_lead_subscriptions_summary_and_omitted_for_marketing(self):
        sub = make_subscription(self.lead, self.agent)
        make_payment(sub, "250", date.today())
        data = self.call(self.manager, "get_lead", {"lead_uuid": str(self.lead.pk)})["structuredContent"]
        self.assertEqual(data["subscriptions"][0]["paid_amount"], "250.00")
        self.assertEqual(data["subscriptions"][0]["amount"], "1000.00")
        # creator in a non-sales department: lead visible, subscriptions omitted
        Department.objects.filter(pk=self.other_agent.department_id).update(code=DepartmentCodes.MARKETING)
        self.other_agent.refresh_from_db()
        res = self.call(self.other_agent, "get_lead", {"lead_uuid": str(self.lead.pk)})
        self.assertFalse(res["isError"])
        self.assertNotIn("subscriptions", res["structuredContent"])

    def test_list_subscriptions_scoping(self):
        sub = make_subscription(self.lead, self.agent)
        res = self.call(self.manager, "list_subscriptions", {"kind": "new"})
        self.assertEqual([i["uuid"] for i in res["structuredContent"]["items"]], [str(sub.pk)])
        res = self.call(self.agent, "list_subscriptions", {"lead_uuid": str(self.lead.pk)})
        self.assertEqual(res["structuredContent"]["count"], 1)
        res = self.call(self.manager, "list_subscriptions", {"kind": "renewal"})
        self.assertEqual(res["structuredContent"]["count"], 0)
        res = self.call(self.hr, "list_subscriptions", {})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "forbidden")

    def test_hidden_leads(self):
        Lead = type(self.lead)
        Lead.objects.filter(pk=self.lead.pk).update(is_hidden=True)
        res = self.call(self.manager, "get_lead", {"lead_uuid": str(self.lead.pk)})
        self.assertFalse(res["isError"])
        self.assertTrue(res["structuredContent"]["is_hidden"])
        res = self.call(self.agent, "get_lead", {"lead_uuid": str(self.lead.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        res = self.call(self.manager, "search_leads", {"hidden": True})
        self.assertEqual([i["uuid"] for i in res["structuredContent"]["items"]], [str(self.lead.pk)])
        self.assertTrue(res["structuredContent"]["items"][0]["is_hidden"])
        res = self.call(self.manager, "search_leads", {})
        self.assertNotIn(str(self.lead.pk), [i["uuid"] for i in res["structuredContent"]["items"]])
        res = self.call(self.agent, "search_leads", {"hidden": True})
        self.assertEqual(res["structuredContent"]["error"], "forbidden")

    def test_sales_totals_own_for_agent(self):
        sub = make_subscription(self.lead, self.agent)
        make_payment(sub, "400", date.today())
        res = self.call(self.agent, "sales_totals", {})
        self.assertFalse(res["isError"])
        data = res["structuredContent"]
        self.assertEqual([r["seller"]["uuid"] for r in data["sellers"]], [str(self.agent.pk)])
        self.assertEqual(data["sellers"][0]["deal_count"], 1)
        self.assertEqual(data["total"]["sales_amount"], "400.00")
        self.assertEqual(data["sellers"][0]["by_kind"]["new"]["deal_count"], 1)

    def test_sales_totals_manager_scope_and_hr_hidden_owner(self):
        for seller, name in ((self.agent, "a"), (self.other_agent, "b"), (self.owner, "c")):
            lead = make_lead(seller, name=name)
            make_payment(make_subscription(lead, seller), "100", date.today())
        data = self.call(self.manager, "sales_totals", {})["structuredContent"]
        got = {r["seller"]["uuid"] for r in data["sellers"]}
        self.assertEqual(got, {str(self.agent.pk), str(self.manager.pk)})
        self.assertEqual(data["total"]["deal_count"], 1)
        res = self.call(self.manager, "sales_totals", {"seller_uuid": str(self.other_agent.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        res = self.call(self.hr, "sales_totals", {"seller_uuid": str(self.owner.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        data = self.call(self.hr, "sales_totals", {})["structuredContent"]
        self.assertEqual([r["seller"]["uuid"] for r in data["sellers"]], [str(self.hr.pk)])
        res = self.call(self.manager, "sales_totals", {"period": "2020-13"})
        self.assertTrue(res["isError"])
