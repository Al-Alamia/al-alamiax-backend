import datetime

from apps.attendance.models import AttendanceDay
from apps.attendance.tests.factories import make_leave_type, make_request
from apps.attendance.types import DayStatus, RequestKind, RequestStatus
from apps.mcp_server.registry import call_tool, load_tools
from apps.mcp_server.tests.base import McpTestCase
from apps.mcp_server.tools.attendance import visible_request
from apps.mcp_server.errors import ToolError

TODAY = datetime.date.today()


def mkday(user, status, date=TODAY, **kw):
    kw.setdefault("evaluated_at", datetime.datetime(2026, 1, 1))
    return AttendanceDay.objects.create(user=user, date=date, status=status, **kw)


class AttendanceToolsTests(McpTestCase):
    def setUp(self):
        super().setUp()
        load_tools()

    def call(self, user, name, args=None):
        return call_tool(user, name, args or {})

    def test_attendance_day_groups_and_scope(self):
        mkday(self.agent, DayStatus.LATE, late_minutes=25)
        mkday(self.manager, DayStatus.PRESENT)
        mkday(self.other_agent, DayStatus.ABSENT)
        res = self.call(self.manager, "attendance_day")
        self.assertFalse(res["isError"])
        g = res["structuredContent"]["groups"]
        self.assertEqual([r["uuid"] for r in g["late"]], [str(self.agent.pk)])
        self.assertEqual(g["late"][0]["late_minutes"], 25)
        self.assertEqual(g["absent"], [])
        self.assertEqual(len(g["present"]), 1)
        self.assertEqual(AttendanceDay.objects.count(), 3)  # read-only

    def test_attendance_day_department_and_hidden_owner(self):
        mkday(self.other_agent, DayStatus.ABSENT)
        mkday(self.owner, DayStatus.PRESENT)
        res = self.call(self.hr, "attendance_day", {"department": "other"})
        g = res["structuredContent"]["groups"]
        self.assertEqual([r["uuid"] for r in g["absent"]], [str(self.other_agent.pk)])
        res = self.call(self.hr, "attendance_day")
        uuids = {r["uuid"] for rows in res["structuredContent"]["groups"].values() for r in rows}
        self.assertNotIn(str(self.owner.pk), uuids)
        self.assertTrue(self.call(self.hr, "attendance_day", {"department": "nope"})["isError"])

    def test_attendance_summary(self):
        mkday(self.agent, DayStatus.PRESENT)
        mkday(self.agent, DayStatus.LATE, date=TODAY - datetime.timedelta(days=1), late_minutes=10)
        res = self.call(self.manager, "attendance_summary", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(res["isError"])
        s = res["structuredContent"]["summary"]
        self.assertLessEqual(s["present"] + s["late"], 2)
        self.assertIn("balances", res["structuredContent"]["leave"])

    def test_attendance_summary_other_dept_and_hidden(self):
        self.assertTrue(self.call(self.manager, "attendance_summary",
                                  {"user_uuid": str(self.other_agent.pk)})["isError"])
        res = self.call(self.hr, "attendance_summary", {"user_uuid": str(self.owner.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        self.assertTrue(self.call(self.agent, "attendance_summary", {"period": "2026-13"})["isError"])

    def test_list_requests_scopes(self):
        mine = make_request(self.agent, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        other = make_request(self.other_agent, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        res = self.call(self.manager, "list_requests")
        self.assertEqual([i["uuid"] for i in res["structuredContent"]["items"]], [str(mine.pk)])
        res = self.call(self.manager, "list_requests", {"scope": "all", "limit": 100})
        uuids = {i["uuid"] for i in res["structuredContent"]["items"]}
        self.assertEqual(uuids, {str(mine.pk)})
        res = self.call(self.hr, "list_requests", {"scope": "all", "kind": "GENERAL"})
        self.assertEqual({i["uuid"] for i in res["structuredContent"]["items"]}, {str(mine.pk), str(other.pk)})
        res = self.call(self.agent, "list_requests", {"scope": "mine"})
        self.assertEqual([i["uuid"] for i in res["structuredContent"]["items"]], [str(mine.pk)])

    def test_list_requests_hr_does_not_see_owner(self):
        make_request(self.owner, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        res = self.call(self.hr, "list_requests", {"scope": "all"})
        self.assertEqual(res["structuredContent"]["items"], [])

    def test_get_request_and_can_decide(self):
        req = make_request(self.agent, RequestKind.GENERAL, TODAY, status=RequestStatus.PENDING)
        res = self.call(self.manager, "get_request", {"request_uuid": str(req.pk)})
        self.assertFalse(res["isError"])
        self.assertTrue(res["structuredContent"]["can_decide"])
        res = self.call(self.agent, "get_request", {"request_uuid": str(req.pk)})
        self.assertFalse(res["structuredContent"]["can_decide"])

    def test_get_request_not_visible(self):
        req = make_request(self.other_agent, RequestKind.GENERAL, TODAY)
        res = self.call(self.manager, "get_request", {"request_uuid": str(req.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        owner_req = make_request(self.owner, RequestKind.GENERAL, TODAY)
        with self.assertRaises(ToolError) as cm:
            visible_request(self.hr, owner_req.pk)
        self.assertEqual(cm.exception.type, "not_found")
        self.assertEqual(visible_request(self.hr, req.pk).pk, req.pk)

    def test_leave_balances(self):
        make_leave_type(name="Annual", uses_balance=True, yearly_allowance=21)
        res = self.call(self.agent, "leave_balances")
        self.assertEqual(res["structuredContent"]["balances"][0]["leave_type"]["name"], "Annual")
        self.assertTrue(self.call(self.manager, "leave_balances",
                                  {"user_uuid": str(self.other_agent.pk)})["isError"])
        self.assertTrue(self.call(self.hr, "leave_balances", {"user_uuid": str(self.owner.pk)})["isError"])
        res = self.call(self.manager, "leave_balances", {"user_uuid": str(self.agent.pk), "year": 2025})
        self.assertEqual(res["structuredContent"]["year"], 2025)
