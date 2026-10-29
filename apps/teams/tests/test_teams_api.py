from datetime import date
from uuid import uuid4

from apps.teams.models import Team
from apps.teams.tests.factories import make_plan, make_team, make_version
from apps.teams.types import PlanKind
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

TEAMS, META, MY = "/api/teams/teams", "/api/teams/meta", "/api/teams/my"
FLAT = [{"min_value": "0", "max_value": None, "kind": "flat", "value": "100"}]


def mk(name, role, dept):
    return User.objects.create_user(username=name, password="x", role=role, department=dept)


class TeamsApiBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.sales = Department.objects.create(name="Sales", code="sales")
        self.mkt = Department.objects.create(name="Marketing", code="marketing")
        self.owner = self.superuser
        self.hr = mk("hr", UserTypes.HR, self.sales)
        self.sales_mgr = mk("smgr", UserTypes.MANAGER, self.sales)
        self.mkt_mgr = mk("mmgr", UserTypes.MANAGER, self.mkt)
        self.leader = mk("lead", UserTypes.AGENT, self.sales)
        self.a1 = mk("a1", UserTypes.AGENT, self.sales)
        self.a2 = mk("a2", UserTypes.AGENT, self.sales)
        self.sales_team = make_team(self.sales, "Sales Team", leader=self.leader, agents=[self.a1])
        self.mkt_team = make_team(self.mkt, "Mkt Team")

    def get(self, user, url, **kw):
        self.authenticate_as(user)
        return self.client.get(url, kw)

    def send(self, method, user, url, data=None):
        self.authenticate_as(user)
        return getattr(self.client, method)(url, data, format="json")

    def url(self, team, suffix=""):
        return f"{TEAMS}/{team.uuid}{suffix}"


class ListTests(TeamsApiBase):
    def names(self, user, **kw):
        r = self.get(user, TEAMS, **kw)
        self.assertEqual(r.status_code, 200)
        return {t["name"] for t in r.data}

    def test_owner_and_hr_see_all(self):
        self.assertEqual(self.names(self.owner), {"Sales Team", "Mkt Team"})
        self.assertEqual(self.names(self.hr), {"Sales Team", "Mkt Team"})

    def test_manager_sees_own_department_only(self):
        self.assertEqual(self.names(self.sales_mgr), {"Sales Team"})

    def test_agent_sees_own_teams_only(self):
        self.assertEqual(self.names(self.a1), {"Sales Team"})
        self.assertEqual(self.names(self.leader), {"Sales Team"})
        self.assertEqual(self.names(self.a2), set())

    def test_item_shape_and_can_edit(self):
        r = self.get(self.sales_mgr, TEAMS)
        item = r.data[0]
        self.assertEqual(set(item), {"uuid", "name", "department", "leader", "agents",
                                     "include_leader_in_total", "is_active", "has_plan", "can_edit"})
        self.assertTrue(item["can_edit"])
        self.assertFalse(item["has_plan"])
        self.assertEqual(item["leader"]["uuid"], str(self.leader.uuid))
        self.assertFalse(self.get(self.hr, TEAMS).data[0]["can_edit"])
        self.assertFalse(self.get(self.a1, TEAMS).data[0]["can_edit"])

    def test_has_plan(self):
        make_plan(PlanKind.TEAM, team=self.sales_team)
        data = {t["name"]: t for t in self.get(self.owner, TEAMS).data}
        self.assertTrue(data["Sales Team"]["has_plan"])
        self.assertFalse(data["Mkt Team"]["has_plan"])

    def test_filters(self):
        self.assertEqual(self.names(self.owner, department=str(self.mkt.uuid)), {"Mkt Team"})
        self.assertEqual(self.names(self.owner, search="sales"), {"Sales Team"})
        self.assertEqual(self.get(self.owner, TEAMS, department="bad").status_code, 400)

    def test_archived_hidden_unless_requested_by_manager(self):
        self.send("delete", self.sales_mgr, self.url(self.sales_team))
        self.assertEqual(self.names(self.sales_mgr), set())
        self.assertEqual(self.names(self.sales_mgr, include_archived="1"), {"Sales Team"})
        self.assertEqual(self.names(self.a1, include_archived="1"), set())


class CreateTests(TeamsApiBase):
    def body(self, **kw):
        base = {"name": "New", "department": str(self.sales.uuid)}
        base.update(kw)
        return base

    def test_manager_creates_in_own_department(self):
        r = self.send("post", self.sales_mgr, TEAMS, self.body(
            leader=str(self.a2.uuid), agents=[str(self.a1.uuid)], include_leader_in_total=True))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["leader"]["uuid"], str(self.a2.uuid))
        self.assertEqual([a["uuid"] for a in r.data["agents"]], [str(self.a1.uuid)])
        self.assertTrue(r.data["include_leader_in_total"])

    def test_other_department_and_hr_forbidden(self):
        r = self.send("post", self.sales_mgr, TEAMS, self.body(department=str(self.mkt.uuid)))
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        self.assertEqual(self.send("post", self.hr, TEAMS, self.body()).status_code, 403)
        self.assertEqual(self.send("post", self.a1, TEAMS, self.body()).status_code, 403)

    def test_duplicate_name_case_insensitive(self):
        r = self.send("post", self.sales_mgr, TEAMS, self.body(name="sales TEAM"))
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate_name"))
        self.assertEqual(Team.objects.count(), 2)

    def test_same_name_in_other_department_or_archived_ok(self):
        self.assertEqual(self.send("post", self.owner, TEAMS, self.body(
            name="Mkt Team")).status_code, 201)
        self.send("delete", self.sales_mgr, self.url(self.sales_team))
        self.assertEqual(self.send("post", self.sales_mgr, TEAMS, self.body(
            name="Sales Team")).status_code, 201)

    def test_leader_in_agents_rejected(self):
        r = self.send("post", self.sales_mgr, TEAMS, self.body(
            leader=str(self.a1.uuid), agents=[str(self.a1.uuid)]))
        self.assertEqual((r.status_code, r.data["type"]), (400, "leader_is_agent"))
        self.assertEqual(Team.objects.count(), 2)

    def test_validation(self):
        for body in (self.body(name=""), self.body(department="x"), self.body(department=str(uuid4())),
                     self.body(leader=str(uuid4())), self.body(agents=[str(uuid4())])):
            r = self.send("post", self.owner, TEAMS, body)
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), body)


class DetailTests(TeamsApiBase):
    def test_patch_rename_and_flag(self):
        r = self.send("patch", self.sales_mgr, self.url(self.sales_team),
                      {"name": "Renamed", "include_leader_in_total": True})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["name"], "Renamed")
        self.assertTrue(r.data["include_leader_in_total"])

    def test_patch_duplicate_name(self):
        make_team(self.sales, "Other")
        r = self.send("patch", self.sales_mgr, self.url(self.sales_team), {"name": "OTHER"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate_name"))
        r = self.send("patch", self.sales_mgr, self.url(self.sales_team), {"name": "sales team"})
        self.assertEqual(r.status_code, 200)

    def test_patch_leader_falsy_values_rejected(self):
        for bad in (0, False, ""):
            r = self.send("patch", self.sales_mgr, self.url(self.sales_team), {"leader": bad})
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), bad)
        self.sales_team.refresh_from_db()
        self.assertEqual(self.sales_team.leader, self.leader)

    def test_patch_leader_set_and_clear(self):
        r = self.send("patch", self.sales_mgr, self.url(self.sales_team), {"leader": str(self.a1.uuid)})
        self.assertEqual(r.data["leader"]["uuid"], str(self.a1.uuid))
        self.assertEqual(r.data["agents"], [])
        r = self.send("patch", self.sales_mgr, self.url(self.sales_team), {"leader": None})
        self.assertIsNone(r.data["leader"])

    def test_patch_department_must_be_manageable(self):
        r = self.send("patch", self.sales_mgr, self.url(self.sales_team), {"department": str(self.mkt.uuid)})
        self.assertEqual(r.status_code, 403)
        r = self.send("patch", self.owner, self.url(self.sales_team), {"department": str(self.mkt.uuid)})
        self.assertEqual(r.data["department"]["name"], "Marketing")

    def test_delete_archives_team_plan(self):
        plan = make_plan(PlanKind.TEAM, team=self.sales_team)
        self.send("delete", self.sales_mgr, self.url(self.sales_team))
        plan.refresh_from_db()
        self.assertFalse(plan.is_active)

    def test_delete_archives(self):
        r = self.send("delete", self.sales_mgr, self.url(self.sales_team))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["is_active"])
        self.sales_team.refresh_from_db()
        self.assertFalse(self.sales_team.is_active)

    def test_agent_write_forbidden(self):
        for method in ("patch", "delete"):
            r = self.send(method, self.a1, self.url(self.sales_team), {"name": "x"})
            self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))
        self.assertEqual(self.get(self.a1, self.url(self.sales_team)).status_code, 200)

    def test_hr_reads_but_cannot_write(self):
        self.assertEqual(self.get(self.hr, self.url(self.sales_team)).status_code, 200)
        self.assertEqual(self.send("patch", self.hr, self.url(self.sales_team), {"name": "x"}).status_code, 403)

    def test_invisible_is_404(self):
        for r in (self.get(self.mkt_mgr, self.url(self.sales_team)),
                  self.send("patch", self.mkt_mgr, self.url(self.sales_team), {"name": "x"}),
                  self.send("post", self.mkt_mgr, self.url(self.sales_team, "/members"), {"add": []}),
                  self.get(self.a2, self.url(self.sales_team)),
                  self.get(self.owner, f"{TEAMS}/{uuid4()}")):
            self.assertEqual((r.status_code, r.data["type"]), (404, "not_found"))

    def test_manager_without_department_manages_nothing(self):
        nodept = mk("nodept", UserTypes.MANAGER, None)
        self.assertEqual(self.get(nodept, TEAMS).data, [])
        self.assertEqual(self.send("post", nodept, TEAMS, {
            "name": "x", "department": str(self.sales.uuid)}).status_code, 403)
        self.assertEqual(self.get(nodept, META).data,
                         {"can_manage": False, "manageable_departments": []})


class MembersTests(TeamsApiBase):
    def test_add_and_remove(self):
        r = self.send("post", self.sales_mgr, self.url(self.sales_team, "/members"),
                      {"add": [str(self.a2.uuid)], "remove": [str(self.a1.uuid)]})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([a["uuid"] for a in r.data["agents"]], [str(self.a2.uuid)])

    def test_add_two(self):
        r = self.send("post", self.sales_mgr, self.url(self.sales_team, "/members"),
                      {"add": [str(self.a2.uuid), str(self.hr.uuid)]})
        self.assertEqual(len(r.data["agents"]), 3)

    def test_add_and_remove_same_user_rejected(self):
        r = self.send("post", self.sales_mgr, self.url(self.sales_team, "/members"),
                      {"add": [str(self.a2.uuid)], "remove": [str(self.a2.uuid)]})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        self.assertFalse(self.sales_team.agents.filter(pk=self.a2.pk).exists())

    def test_leader_is_agent(self):
        r = self.send("post", self.sales_mgr, self.url(self.sales_team, "/members"),
                      {"add": [str(self.leader.uuid)]})
        self.assertEqual((r.status_code, r.data["type"]), (400, "leader_is_agent"))

    def test_invalid_users(self):
        url = self.url(self.sales_team, "/members")
        self.a2.is_active = False
        self.a2.save()
        for add in ([str(uuid4())], ["nope"], [str(self.a2.uuid)], "x",
                    [str(uuid4()) for _ in range(201)]):
            r = self.send("post", self.sales_mgr, url, {"add": add})
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), add)

    def test_agent_forbidden(self):
        r = self.send("post", self.a1, self.url(self.sales_team, "/members"), {"add": []})
        self.assertEqual(r.status_code, 403)


class MetaMyTests(TeamsApiBase):
    def test_meta(self):
        r = self.get(self.sales_mgr, META)
        self.assertEqual(r.data, {"can_manage": True, "manageable_departments": [
            {"uuid": str(self.sales.uuid), "name": "Sales"}]})
        self.assertEqual(self.get(self.a1, META).data, {"can_manage": False, "manageable_departments": []})
        self.assertEqual(self.get(self.hr, META).data["can_manage"], False)
        owner = self.get(self.owner, META).data
        self.assertTrue(owner["can_manage"])
        self.assertEqual(len(owner["manageable_departments"]), Department.objects.count())

    def test_my_leader(self):
        dp = make_plan(PlanKind.PERSONAL, department=self.sales)
        make_version(dp, date(2020, 1, 1), FLAT)
        tp = make_plan(PlanKind.TEAM, team=self.sales_team)
        make_version(tp, date(2020, 1, 1), FLAT)
        make_version(tp, date(2020, 6, 1), FLAT)
        r = self.get(self.leader, MY)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([t["name"] for t in r.data["teams_led"]], ["Sales Team"])
        self.assertEqual(r.data["teams_member"], [])
        self.assertEqual([p["uuid"] for p in r.data["personal_plans"]], [str(dp.uuid)])
        self.assertEqual(r.data["personal_plans"][0]["target"]["type"], "department")
        self.assertFalse(r.data["personal_plans"][0]["can_edit"])
        self.assertEqual([p["uuid"] for p in r.data["team_plans"]], [str(tp.uuid)])
        plan = r.data["team_plans"][0]
        self.assertEqual(plan["versions"], ["2020-06", "2020-01"])
        self.assertEqual(plan["current_version"], {"effective_from": "2020-06", "metric": "lead_count",
            "american_threshold_percent": None, "tiers": [
            {"variant": "normal", "min_value": "0.00", "max_value": None, "kind": "flat", "value": "100.00"}]})

    def test_my_member_and_no_plan(self):
        r = self.get(self.a1, MY)
        self.assertEqual([t["name"] for t in r.data["teams_member"]], ["Sales Team"])
        self.assertEqual((r.data["teams_led"], r.data["personal_plans"], r.data["team_plans"]), ([], [], []))

    def test_plan_can_edit_for_manager(self):
        from apps.teams.serializers import plan_data
        dp = make_plan(PlanKind.PERSONAL, department=self.sales)
        self.assertTrue(plan_data(dp, self.sales_mgr, date.today())["can_edit"])
        self.assertFalse(plan_data(dp, self.mkt_mgr, date.today())["can_edit"])
        self.assertIsNone(plan_data(dp, self.owner, date.today())["current_version"])
