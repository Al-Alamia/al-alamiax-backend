import datetime

from apps.activity.services.events import record_event
from apps.mcp_server.registry import call_tool, load_tools
from apps.mcp_server.tests.base import McpTestCase
from apps.reports.models import ReportType
from apps.treasury.models import ProjectGroup
from apps.treasury.services import ledger
from apps.users.models import Department


class MiscToolsTests(McpTestCase):
    def setUp(self):
        super().setUp()
        load_tools()
        self.today = datetime.date.today()

    def call(self, user, name, args=None):
        return call_tool(user, name, args or {})

    def err(self, res):
        self.assertTrue(res["isError"])
        return res["structuredContent"]["error"]

    # treasury
    def test_treasury_owner_happy(self):
        g = ProjectGroup.objects.create(name="G", created_by=self.owner)
        ledger.add_entry(self.owner, "in", "income", "100", self.today, "x")
        ledger.add_entry(self.owner, "out", "operating", "30", self.today, "y", g)
        d = self.call(self.owner, "treasury_balance")["structuredContent"]
        self.assertEqual((d["income"], d["outcome"], d["net"]), ("100.00", "30.00", "70.00"))
        d = self.call(self.owner, "treasury_balance", {"group_uuid": str(g.pk)})["structuredContent"]
        self.assertEqual((d["income"], d["outcome"]), ("0.00", "30.00"))
        res = self.call(self.owner, "list_treasury_entries", {"kind": "out"})["structuredContent"]
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["items"][0]["amount"], "30.00")
        res = self.call(self.owner, "list_treasury_entries", {})["structuredContent"]
        self.assertEqual(res["count"], 2)

    def test_manager_cannot_call_treasury(self):
        for name in ("treasury_balance", "list_treasury_entries"):
            self.assertEqual(self.err(self.call(self.manager, name)), "unknown_tool")

    # reports
    def test_report_types_and_board(self):
        rt = ReportType.objects.create(name="R", frequency="daily")
        rt.departments.set([self.department])
        res = self.call(self.manager, "list_report_types")["structuredContent"]
        self.assertEqual(res["items"][0]["name"], "R")
        b = self.call(self.manager, "report_board", {"report_type_uuid": str(rt.pk)})["structuredContent"]
        uuids = {r["user"]["uuid"] for r in b["rows"]}
        self.assertIn(str(self.agent.pk), uuids)
        self.assertNotIn(str(self.other_agent.pk), uuids)

    def test_reports_forbidden_for_agent(self):
        self.assertEqual(self.err(self.call(self.agent, "list_report_types")), "forbidden")

    def test_board_hides_owner_from_hr(self):
        rt = ReportType.objects.create(name="R2", frequency="daily")
        rt.departments.set([self.owner.department])
        b = self.call(self.hr, "report_board", {"report_type_uuid": str(rt.pk)})["structuredContent"]
        self.assertNotIn(str(self.owner.pk), {r["user"]["uuid"] for r in b["rows"]})

    # dashboards
    def test_home_and_marketing(self):
        d = self.call(self.agent, "home_dashboard")["structuredContent"]
        self.assertIn("widgets", d)
        m = self.call(self.manager, "marketing_dashboard", {"month": self.today.strftime("%Y-%m")})
        self.assertFalse(m["isError"])
        self.assertIn("total", m["structuredContent"])
        self.assertEqual(self.err(self.call(self.manager, "marketing_dashboard", {"month": "2026-13"})),
                         "invalid_arguments")

    # activity
    def test_team_activity_scope(self):
        record_event(self.agent, "user.updated", subject=self.agent)
        record_event(self.other_agent, "user.updated", subject=self.other_agent)
        res = self.call(self.manager, "team_activity")["structuredContent"]
        subjects = {e["subject"]["uuid"] for e in res["items"] if e["subject"]}
        self.assertEqual(subjects, {str(self.agent.pk)})
        self.assertIn(str(self.agent.pk), {p["uuid"] for p in res["presence"]})
        self.assertNotIn(str(self.other_agent.pk), {p["uuid"] for p in res["presence"]})
        self.assertEqual(self.err(self.call(self.manager, "team_activity",
                                            {"user_uuid": str(self.other_agent.pk)})), "not_found")
        self.assertEqual(self.err(self.call(self.other_agent, "team_activity")), "forbidden")

    def test_team_activity_hr_cannot_see_owner(self):
        record_event(self.owner, "user.updated", subject=self.owner)
        self.assertEqual(self.err(self.call(self.hr, "team_activity", {"user_uuid": str(self.owner.pk)})),
                         "not_found")
        res = self.call(self.hr, "team_activity")["structuredContent"]
        self.assertNotIn(str(self.owner.pk), {p["uuid"] for p in res["presence"]})
        for e in res["items"]:
            for ref in (e["actor"], e["subject"]):
                self.assertNotEqual((ref or {}).get("uuid"), str(self.owner.pk))

    def test_board_summary_excludes_hidden_users(self):
        rt = ReportType.objects.create(name="R3", frequency="daily")
        rt.departments.set([self.owner.department])
        full = self.call(self.hr, "report_board", {"report_type_uuid": str(rt.pk)})["structuredContent"]
        total = sum(full["summary"][k] for k in ("submitted", "late", "missing", "not_required"))
        self.assertEqual(total, len(full["rows"]))
        self.assertNotIn(str(self.owner.pk), {r["user"]["uuid"] for r in full["rows"]})

    def test_team_activity_drops_hidden_events_entirely(self):
        record_event(self.owner, "user.updated", subject=self.agent, label="OWNERLABEL")
        record_event(self.agent, "user.updated", subject=self.owner, label="OWNERLABEL")
        res = self.call(self.hr, "team_activity")["structuredContent"]
        self.assertNotIn("OWNERLABEL", str(res["items"]))
        self.assertEqual(res["truncated"], False)
