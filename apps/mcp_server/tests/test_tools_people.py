import datetime
from decimal import Decimal

from apps.mcp_server.registry import call_tool, load_tools, visible_tools
from apps.mcp_server.tests.base import McpTestCase
from apps.teams.models import CommissionPlan, PlanVersion, Team, Tier
from apps.teams.types import PlanKind, PlanMetric, TierKind
from apps.users.models import Profile
from apps.users.types import UserTypes


class PeopleToolsTests(McpTestCase):
    def setUp(self):
        super().setUp()
        load_tools()
        self.team = Team.objects.get(name="T")

    def call(self, user, name, args=None):
        return call_tool(user, name, args or {})

    # whoami
    def test_whoami_lists_tool_names(self):
        res = self.call(self.manager, "whoami")
        self.assertFalse(res["isError"])
        data = res["structuredContent"]
        self.assertEqual(data["uuid"], str(self.manager.pk))
        self.assertEqual(data["role"], UserTypes.MANAGER)
        self.assertFalse(data["is_superuser"])
        self.assertEqual(data["tools"], sorted(t.name for t in visible_tools(self.manager)))
        self.assertIn("whoami", data["tools"])

    # search_users
    def test_search_users_manager_scoped_to_department(self):
        res = self.call(self.manager, "search_users", {"limit": 100})
        uuids = {i["uuid"] for i in res["structuredContent"]["items"]}
        self.assertIn(str(self.agent.pk), uuids)
        self.assertNotIn(str(self.other_agent.pk), uuids)

    def test_search_users_query_and_role(self):
        res = self.call(self.hr, "search_users", {"query": "other_ag", "role": "AGENT"})
        items = res["structuredContent"]["items"]
        self.assertEqual([i["uuid"] for i in items], [str(self.other_agent.pk)])
        self.assertTrue(items[0]["is_active"])

    def test_search_users_department_filter(self):
        res = self.call(self.hr, "search_users", {"department": "other", "limit": 100})
        uuids = {i["uuid"] for i in res["structuredContent"]["items"]}
        self.assertIn(str(self.other_agent.pk), uuids)
        self.assertNotIn(str(self.agent.pk), uuids)
        res = self.call(self.hr, "search_users", {"department": str(self.department.pk), "limit": 100})
        uuids = {i["uuid"] for i in res["structuredContent"]["items"]}
        self.assertIn(str(self.agent.pk), uuids)
        self.assertNotIn(str(self.other_agent.pk), uuids)

    def test_search_users_active_filter(self):
        self.other_agent.is_active = False
        self.other_agent.save()
        res = self.call(self.hr, "search_users", {"limit": 100})
        self.assertNotIn(str(self.other_agent.pk),
                         {i["uuid"] for i in res["structuredContent"]["items"]})
        res = self.call(self.hr, "search_users", {"active": False})
        self.assertEqual([i["uuid"] for i in res["structuredContent"]["items"]],
                         [str(self.other_agent.pk)])

    def test_hr_cannot_see_owner(self):
        res = self.call(self.hr, "search_users", {"limit": 100})
        self.assertNotIn(str(self.owner.pk), {i["uuid"] for i in res["structuredContent"]["items"]})
        res = self.call(self.hr, "get_user", {"user_uuid": str(self.owner.pk)})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        res = self.call(self.owner, "get_user", {"user_uuid": str(self.owner.pk)})
        self.assertFalse(res["isError"])

    def test_agent_search_is_empty(self):
        res = self.call(self.agent, "search_users")
        self.assertEqual(res["structuredContent"]["items"], [])

    # get_user
    def test_get_user_happy_path(self):
        Profile.objects.update_or_create(user=self.agent, defaults={"phone": "01000000000"})
        res = self.call(self.manager, "get_user", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(res["isError"])
        data = res["structuredContent"]
        self.assertEqual(data["uuid"], str(self.agent.pk))
        self.assertEqual(data["phone"], "01000000000")
        self.assertNotIn("email", data)
        self.assertEqual(data["teams"], [{"uuid": str(self.team.pk), "name": "T"}])

    def test_get_user_leader_teams(self):
        res = self.call(self.hr, "get_user", {"user_uuid": str(self.leader.pk)})
        self.assertEqual([t["name"] for t in res["structuredContent"]["teams"]], ["T"])

    def test_manager_other_department_not_found(self):
        res = self.call(self.manager, "get_user", {"user_uuid": str(self.other_agent.pk)})
        self.assertTrue(res["isError"])
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    def test_get_user_self(self):
        res = self.call(self.agent, "get_user", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(res["isError"])

    # teams
    def test_list_teams(self):
        res = self.call(self.manager, "list_teams")
        self.assertEqual([i["name"] for i in res["structuredContent"]["items"]], ["T"])
        item = res["structuredContent"]["items"][0]
        # the fixture leader sits in another department, so the manager may not see them
        self.assertIsNone(item["leader"])
        hr_items = self.call(self.hr, "list_teams")["structuredContent"]["items"]
        hr_item = next(i for i in hr_items if i["uuid"] == str(self.team.pk))
        self.assertEqual(hr_item["leader"]["uuid"], str(self.leader.pk))
        self.assertEqual(item["member_count"], 1)

    def test_list_teams_other_scope(self):
        other_team = Team.objects.create(name="Z", department=self.other_agent.department)
        res = self.call(self.manager, "list_teams")
        self.assertNotIn(str(other_team.pk), {i["uuid"] for i in res["structuredContent"]["items"]})
        res = self.call(self.hr, "list_teams", {"department": "other"})
        self.assertEqual([i["name"] for i in res["structuredContent"]["items"]], ["Z"])
        res = self.call(self.other_agent, "list_teams")
        self.assertEqual(res["structuredContent"]["items"], [])

    def test_get_team(self):
        plan = CommissionPlan.objects.create(kind=PlanKind.TEAM, team=self.team,
                                             metric=PlanMetric.LEAD_COUNT)
        v = PlanVersion.objects.create(plan=plan, effective_from=datetime.date(2020, 1, 1))
        Tier.objects.create(version=v, min_value=0, max_value=None, kind=TierKind.FLAT, value=10)
        res = self.call(self.manager, "get_team", {"team_uuid": str(self.team.pk)})
        self.assertFalse(res["isError"])
        data = res["structuredContent"]
        self.assertIsNone(data["leader"])  # leader is in another department
        hr_data = self.call(self.hr, "get_team", {"team_uuid": str(self.team.pk)})["structuredContent"]
        self.assertEqual(hr_data["leader"]["uuid"], str(self.leader.pk))
        self.assertEqual([m["uuid"] for m in data["members"]], [str(self.agent.pk)])
        self.assertEqual(data["department"]["name"], self.department.name)
        self.assertEqual(data["plans"][0]["metric"], "lead_count")
        self.assertEqual(data["plans"][0]["tiers"], 1)

    def test_get_team_not_visible(self):
        other_team = Team.objects.create(name="Z", department=self.other_agent.department)
        res = self.call(self.manager, "get_team", {"team_uuid": str(other_team.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    # get_target_progress
    def _personal_plan(self, user):
        plan = CommissionPlan.objects.create(kind=PlanKind.PERSONAL, user=user,
                                             metric=PlanMetric.LEAD_COUNT)
        v = PlanVersion.objects.create(plan=plan, effective_from=datetime.date(2020, 1, 1))
        Tier.objects.create(version=v, min_value=0, max_value=4, kind=TierKind.FLAT, value=10)
        Tier.objects.create(version=v, min_value=5, max_value=None, kind=TierKind.FLAT, value=50)

    def test_progress_requires_exactly_one_target(self):
        res = self.call(self.manager, "get_target_progress")
        self.assertEqual(res["structuredContent"]["error"], "invalid_arguments")
        res = self.call(self.manager, "get_target_progress",
                        {"user_uuid": str(self.agent.pk), "team_uuid": str(self.team.pk)})
        self.assertEqual(res["structuredContent"]["error"], "invalid_arguments")
        res = self.call(self.manager, "get_target_progress",
                        {"user_uuid": str(self.agent.pk), "month": "2026-13"})
        self.assertEqual(res["structuredContent"]["error"], "invalid_arguments")

    def test_progress_personal(self):
        self._personal_plan(self.agent)
        res = self.call(self.manager, "get_target_progress", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(res["isError"], res)
        p = res["structuredContent"]["progress"][0]
        self.assertEqual(p["metric"], "lead_count")
        self.assertEqual(p["value"], "0")
        self.assertEqual(p["tier_reached"]["max_value"], "4.00")
        self.assertEqual(p["next_tier"]["min_value"], "5.00")

    def test_progress_personal_out_of_scope(self):
        res = self.call(self.manager, "get_target_progress", {"user_uuid": str(self.other_agent.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        res = self.call(self.agent, "get_target_progress", {"user_uuid": str(self.agent.pk)})
        self.assertFalse(res["isError"])
        res = self.call(self.agent, "get_target_progress", {"user_uuid": str(self.leader.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    def test_progress_team(self):
        plan = CommissionPlan.objects.create(kind=PlanKind.TEAM, team=self.team,
                                             metric=PlanMetric.LEAD_COUNT)
        v = PlanVersion.objects.create(plan=plan, effective_from=datetime.date(2020, 1, 1))
        Tier.objects.create(version=v, min_value=0, max_value=None, kind=TierKind.FLAT, value=10)
        res = self.call(self.manager, "get_target_progress", {"team_uuid": str(self.team.pk)})
        self.assertFalse(res["isError"], res)
        p = res["structuredContent"]["progress"][0]
        self.assertEqual(p["value"], "0")
        self.assertEqual(p["tier_reached"]["min_value"], "0.00")
        self.assertIsNone(p["next_tier"])
        other_team = Team.objects.create(name="Z", department=self.other_agent.department)
        res = self.call(self.manager, "get_target_progress", {"team_uuid": str(other_team.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    def test_hr_cannot_see_owner_progress(self):
        res = self.call(self.hr, "get_target_progress", {"user_uuid": str(self.owner.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")
        res = self.call(self.owner, "get_target_progress", {"user_uuid": str(self.superuser.pk)})
        self.assertEqual(res["structuredContent"]["error"], "not_found")

    def test_search_users_does_not_match_email(self):
        res = self.call(self.hr, "search_users", {"query": "other_agent@t.com"})
        self.assertEqual(res["structuredContent"]["items"], [])

    def test_get_user_teams_filtered_by_viewer_scope(self):
        # other_agent's department manager is not in play: put other_agent in a team of another dept
        hidden = Team.objects.create(name="Hidden", department=self.other_agent.department)
        hidden.agents.add(self.agent)
        res = self.call(self.manager, "get_user", {"user_uuid": str(self.agent.pk)})
        self.assertEqual([t["name"] for t in res["structuredContent"]["teams"]], ["T"])
