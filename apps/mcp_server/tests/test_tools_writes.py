import datetime

from django.utils import timezone

from apps.activity.models import ActivityEvent
from apps.attendance.models import PeriodClose
from apps.attendance.tests.factories import make_request
from apps.attendance.types import RequestKind, RequestStatus
from apps.mcp_server.registry import call_tool, load_tools, tool_descriptor, visible_tools
from apps.mcp_server.tests.base import McpTestCase
from apps.subscriptions.tests.factories import assign, make_lead
from apps.users.models import Department, LeadAssignment
from apps.users.types import AssignmentKinds, DepartmentCodes

TODAY = datetime.date.today()


class WriteToolsTests(McpTestCase):
    def setUp(self):
        super().setUp()
        load_tools()
        Department.objects.filter(pk=self.department.pk).update(code=DepartmentCodes.SALES)
        for u in (self.agent, self.manager, self.leader, self.owner):
            u.refresh_from_db()

    def call(self, user, name, args=None):
        return call_tool(user, name, args or {})

    def pending(self, user=None):
        return make_request(user or self.agent, RequestKind.GENERAL, TODAY,
                            status=RequestStatus.PENDING, details="x")

    def test_approve_ok(self):
        req = self.pending()
        res = self.call(self.manager, "approve_request", {"request_uuid": str(req.pk), "note": "ok"})
        self.assertFalse(res["isError"], res)
        self.assertEqual(res["structuredContent"]["status"], "APPROVED")
        self.assertIn("can_approve", res["structuredContent"])
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.APPROVED)
        ev = ActivityEvent.objects.get(verb="request.approved")
        self.assertEqual(ev.data["via"], "mcp")

    def test_reject_ok(self):
        req = self.pending()
        res = self.call(self.manager, "reject_request", {"request_uuid": str(req.pk), "note": "no"})
        self.assertFalse(res["isError"], res)
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.REJECTED)

    def test_approve_not_decider_forbidden(self):
        req = self.pending()
        res = self.call(self.agent, "approve_request", {"request_uuid": str(req.pk)})  # own, visible
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "forbidden")
        res = self.call(self.agent, "reject_request", {"request_uuid": str(req.pk), "note": "x"})
        self.assertEqual(res["structuredContent"]["error"], "forbidden")
        req.refresh_from_db()
        self.assertEqual(req.status, RequestStatus.PENDING)

    def test_approve_invisible_not_found(self):
        req = self.pending(self.other_agent)
        res = self.call(self.manager, "approve_request", {"request_uuid": str(req.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    def test_approve_closed_period(self):
        req = self.pending()
        PeriodClose.objects.create(period="2000-01", start=TODAY - datetime.timedelta(days=10),
                                   end=TODAY + datetime.timedelta(days=10),
                                   closed_by=self.superuser, closed_at=timezone.now())
        res = self.call(self.hr, "approve_request", {"request_uuid": str(req.pk)})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "period_closed")

    def test_reject_requires_note(self):
        req = self.pending()
        res = self.call(self.manager, "reject_request", {"request_uuid": str(req.pk)})
        self.assertEqual(res["structuredContent"]["error"], "invalid_arguments")
        res = self.call(self.manager, "reject_request", {"request_uuid": str(req.pk), "note": ""})
        self.assertEqual(res["structuredContent"]["error"], "invalid_arguments")

    def args(self, leads, agent, kind=AssignmentKinds.SALES.value):
        return {"lead_uuids": [str(x.pk) for x in leads], "agent_uuid": str(agent.pk), "kind": kind}

    def test_assign_ok(self):
        lead = make_lead(self.other_agent)
        res = self.call(self.manager, "assign_leads", self.args([lead], self.agent))
        self.assertFalse(res["isError"], res)
        self.assertEqual(res["structuredContent"]["assigned"], 1)
        self.assertEqual(res["structuredContent"]["agent"]["uuid"], str(self.agent.pk))
        self.assertTrue(LeadAssignment.objects.filter(lead=lead, agent=self.agent, is_active=True).exists())

    def test_assign_agent_not_assignable_forbidden(self):
        lead = make_lead(self.other_agent)
        res = self.call(self.manager, "assign_leads", self.args([lead], self.other_agent))  # not Sales
        self.assertEqual(res["structuredContent"]["error"], "forbidden")
        self.assertFalse(LeadAssignment.objects.filter(lead=lead).exists())

    def test_assign_no_capability(self):
        lead = make_lead(self.other_agent)
        assign(lead, self.agent, by=self.manager)
        res = self.call(self.agent, "assign_leads", self.args([lead], self.agent))
        self.assertEqual(res["structuredContent"]["error"], "unknown_tool")
        names = {t.name for t in visible_tools(self.agent)}
        self.assertNotIn("assign_leads", names)

    def test_assign_unknown_lead_not_found_and_nothing_assigned(self):
        import uuid
        lead = make_lead(self.other_agent)
        res = self.call(self.manager, "assign_leads", {
            "lead_uuids": [str(lead.pk), str(uuid.uuid4())], "agent_uuid": str(self.agent.pk),
            "kind": AssignmentKinds.SALES.value})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        self.assertEqual(LeadAssignment.objects.count(), 0)

    def test_write_tools_annotations(self):
        by = {t.name: tool_descriptor(t) for t in visible_tools(self.manager)}
        for name in ("approve_request", "reject_request", "assign_leads"):
            self.assertIs(by[name]["annotations"]["destructiveHint"], True)
            self.assertIs(by[name]["annotations"]["readOnlyHint"], False)
