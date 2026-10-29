from datetime import date

from apps.teams.models import CommissionPlan
from apps.teams.tests.factories import make_plan, make_team, make_version
from apps.teams.types import PlanKind
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

PLANS, PREVIEW = "/api/teams/plans", "/api/teams/plans/preview"


def mk(name, role, dept):
    return User.objects.create_user(username=name, password="x", role=role, department=dept)


def tier(min_, max_, kind, value, variant="normal"):
    return {"variant": variant, "min_value": str(min_), "max_value": None if max_ is None else str(max_),
            "kind": kind, "value": str(value)}


TIERS = [tier(0, 99, "flat", 0), tier(100, 199, "unit", 10), tier(200, None, "unit", 15)]


def _first(offset=0):
    y, m = map(int, month(offset).split("-"))
    return date(y, m, 1)


def month(offset=0):
    total = date.today().year * 12 + date.today().month - 1 + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


class PlansBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.sales = Department.objects.create(name="Sales", code="sales")
        self.mkt = Department.objects.create(name="Marketing", code="marketing")
        self.owner = self.superuser
        self.smgr = mk("smgr", UserTypes.MANAGER, self.sales)
        self.mmgr = mk("mmgr", UserTypes.MANAGER, self.mkt)
        self.leader = mk("lead", UserTypes.AGENT, self.sales)
        self.agent = mk("salesagent", UserTypes.AGENT, self.sales)
        self.hr = mk("hr", UserTypes.HR, self.sales)
        self.mkt_agent = mk("magent", UserTypes.AGENT, self.mkt)
        self.nodept = mk("nodept", UserTypes.AGENT, None)
        self.sales_team = make_team(self.sales, "Sales Team", leader=self.leader, agents=[self.agent])
        self.mkt_team = make_team(self.mkt, "Mkt Team")

    def send(self, method, user, url, data=None, **kw):
        self.authenticate_as(user)
        return getattr(self.client, method)(url, data, format="json", **kw)

    def post_plan(self, actor, **over):
        body = {"kind": "personal", "metric": "lead_count", "effective_from": month(), "tiers": TIERS}
        body.update(over)
        return self.send("post", actor, PLANS, body)

    def url(self, plan, suffix=""):
        return f"{PLANS}/{plan.uuid}{suffix}"


class CreateTests(PlansBase):
    def test_manager_creates_department_plan(self):
        r = self.post_plan(self.smgr, department=str(self.sales.uuid))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(len(r.data["current_version"]["tiers"]), 3)
        self.assertEqual(r.data["target"]["type"], "department")
        self.assertTrue(r.data["can_edit"])

    def test_duplicate_target(self):
        self.post_plan(self.smgr, department=str(self.sales.uuid))
        r = self.post_plan(self.smgr, department=str(self.sales.uuid))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "duplicate_plan")
        self.assertEqual(CommissionPlan.objects.count(), 1)

    def test_other_department_forbidden(self):
        for extra in ({"department": str(self.mkt.uuid)}, {"user": str(self.mkt_agent.uuid)},
                      {"kind": "team", "team": str(self.mkt_team.uuid)}):
            r = self.post_plan(self.smgr, **extra)
            self.assertEqual(r.status_code, 403, extra)

    def test_forbidden_before_body_validation(self):
        r = self.post_plan(self.smgr, department=str(self.mkt.uuid), tiers="junk", metric="x")
        self.assertEqual(r.status_code, 403)

    def test_user_without_department_top_only(self):
        self.assertEqual(self.post_plan(self.smgr, user=str(self.nodept.uuid)).status_code, 403)
        r = self.post_plan(self.owner, user=str(self.nodept.uuid))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["target"]["type"], "user")

    def test_team_plan(self):
        r = self.post_plan(self.smgr, kind="team", team=str(self.sales_team.uuid))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["kind"], "team")

    def test_agent_forbidden(self):
        r = self.post_plan(self.agent, user=str(self.agent.uuid))
        self.assertEqual(r.status_code, 403)

    def test_past_month(self):
        r = self.post_plan(self.smgr, department=str(self.sales.uuid), effective_from=month(-1))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "past_month")
        self.assertEqual(CommissionPlan.objects.count(), 0)

    def test_invalid_tiers(self):
        bad = [tier(0, 99, "flat", 0), tier(150, None, "flat", 5)]
        r = self.post_plan(self.smgr, department=str(self.sales.uuid), tiers=bad)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "invalid_tiers")
        self.assertEqual(r.data["errors"][0]["index"], 1)
        self.assertEqual(CommissionPlan.objects.count(), 0)

    def test_invalid_inputs(self):
        d = str(self.sales.uuid)
        cases = [
            {"kind": "bogus"}, {"metric": "bogus"}, {"effective_from": "2026-13"},
            {"effective_from": "2026-1"}, {"tiers": "x"},
            {"american_threshold_percent": "abc"}, {"american_threshold_percent": "50", "metric": "deal_count"},
            {"user": str(self.agent.uuid)}, {"department": "nope"}, {"kind": "team"},
        ]
        for extra in cases:
            r = self.post_plan(self.smgr, **{"department": d, **extra})
            self.assertEqual(r.status_code, 400, extra)
            self.assertEqual(r.data["type"], "invalid", extra)

    def test_zero_threshold_rejected(self):
        tiers = TIERS + [tier(0, None, "flat", 50, "american")]
        r = self.post_plan(self.smgr, department=str(self.sales.uuid), tiers=tiers,
                           american_threshold_percent="0")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_hr_forbidden(self):
        r = self.post_plan(self.hr, department=str(self.sales.uuid))
        self.assertEqual(r.status_code, 403)

    def test_post_reactivates_archived_plan(self):
        plan = make_plan(PlanKind.PERSONAL, department=self.sales)
        make_version(plan, date(2020, 1, 1), [tier(0, None, "flat", 1)], metric="deal_count")
        plan.is_active = False
        plan.save()
        r = self.post_plan(self.smgr, department=str(self.sales.uuid), metric="lead_count")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["uuid"], str(plan.uuid))
        self.assertTrue(r.data["is_active"])
        self.assertEqual(r.data["metric"], "lead_count")
        self.assertEqual(r.data["current_version"]["metric"], "lead_count")
        self.assertEqual(len(r.data["current_version"]["tiers"]), 3)
        self.assertEqual(plan.versions.get(effective_from=date(2020, 1, 1)).metric, "deal_count")
        self.assertEqual(CommissionPlan.objects.count(), 1)

    def test_reactivation_failure_rolls_back(self):
        plan = make_plan(PlanKind.PERSONAL, department=self.sales)
        plan.is_active = False
        plan.save()
        r = self.post_plan(self.smgr, department=str(self.sales.uuid), tiers=[tier(0, 9, "flat", 1)] * 2)
        self.assertEqual(r.data["type"], "invalid_tiers")
        plan.refresh_from_db()
        self.assertFalse(plan.is_active)

    def test_threshold_with_american_tiers(self):
        tiers = TIERS + [tier(0, None, "flat", 50, "american")]
        r = self.post_plan(self.smgr, department=str(self.sales.uuid), tiers=tiers,
                           american_threshold_percent="40")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["american_threshold_percent"], "40.00")


class VersionTests(PlansBase):
    def setUp(self):
        super().setUp()
        self.plan = make_plan(PlanKind.PERSONAL, department=self.sales)
        make_version(self.plan, date.today().replace(day=1), [tier(0, None, "flat", 10)])

    def test_put_creates_next_version_and_get_returns_it(self):
        nxt = month(1)
        r = self.send("put", self.smgr, self.url(self.plan, f"/versions/{nxt}"), {"tiers": TIERS})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.plan.versions.count(), 2)
        r = self.send("get", self.smgr, self.url(self.plan, f"/versions/{nxt}"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["tiers"]), 3)
        self.assertEqual(r.data["effective_from"], nxt)

    def test_get_before_first_version_404(self):
        r = self.send("get", self.smgr, self.url(self.plan, f"/versions/{month(-2)}"))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.data["type"], "not_found")

    def test_bad_month(self):
        r = self.send("get", self.smgr, self.url(self.plan, "/versions/2026-13"))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.send("put", self.smgr, self.url(self.plan, "/versions/junk"), {"tiers": TIERS})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_put_past_month(self):
        r = self.send("put", self.smgr, self.url(self.plan, f"/versions/{month(-1)}"), {"tiers": TIERS})
        self.assertEqual((r.status_code, r.data["type"]), (400, "past_month"))

    def test_put_invalid_tiers(self):
        r = self.send("put", self.smgr, self.url(self.plan, f"/versions/{month(1)}"),
                      {"tiers": [tier(0, 9, "flat", 1), tier(50, None, "flat", 1)]})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_tiers"))
        r = self.send("put", self.smgr, self.url(self.plan, f"/versions/{month(1)}"), {"tiers": "x"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_put_permissions(self):
        url = self.url(self.plan, f"/versions/{month(1)}")
        self.assertEqual(self.send("put", self.mmgr, url, {"tiers": TIERS}).status_code, 404)
        self.assertEqual(self.send("put", self.agent, url, {"tiers": TIERS}).status_code, 403)

    def test_get_invisible_404(self):
        r = self.send("get", self.mkt_agent, self.url(self.plan, f"/versions/{month()}"))
        self.assertEqual(r.status_code, 404)


class DetailTests(PlansBase):
    def setUp(self):
        super().setUp()
        self.plan = make_plan(PlanKind.PERSONAL, department=self.sales)
        make_version(self.plan, date.today().replace(day=1), [tier(0, None, "flat", 10)])

    def test_get(self):
        r = self.send("get", self.agent, self.url(self.plan))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["can_edit"])
        self.assertEqual(self.send("get", self.mmgr, self.url(self.plan)).status_code, 404)

    def test_patch_metric_with_tiers(self):
        body = {"metric": "sales_amount", "effective_from": month(1),
                "tiers": [tier(0, "99.99", "percent", 1), tier("100.00", None, "percent", 2)]}
        r = self.send("patch", self.smgr, self.url(self.plan), body)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["metric"], "lead_count")  # current month version untouched
        self.assertEqual(self.plan.versions.get(effective_from=_first(1)).metric, "sales_amount")
        self.assertEqual(self.plan.versions.count(), 2)

    def test_patch_invalid_tiers_rolls_back(self):
        body = {"metric": "sales_amount", "effective_from": month(1), "tiers": [tier(0, 9, "flat", 1)] * 2}
        r = self.send("patch", self.smgr, self.url(self.plan), body)
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_tiers"))
        self.assertEqual(self.plan.versions.count(), 1)

    def test_metric_change_leaves_past_version_unchanged(self):
        from apps.teams.services import evaluate
        current = self.plan.versions.get()
        before = evaluate(current, 5).amount
        body = {"metric": "sales_amount", "effective_from": month(1),
                "tiers": [tier(0, "99.99", "percent", 1), tier("100.00", None, "percent", 2)]}
        self.assertEqual(self.send("patch", self.smgr, self.url(self.plan), body).status_code, 200)
        current.refresh_from_db()
        self.assertEqual(current.metric, "lead_count")
        self.assertEqual(evaluate(current, 5).amount, before)
        r = self.send("get", self.smgr, self.url(self.plan, f"/versions/{month()}"))
        self.assertEqual(r.data["metric"], "lead_count")
        r = self.send("get", self.smgr, self.url(self.plan, f"/versions/{month(1)}"))
        self.assertEqual(r.data["metric"], "sales_amount")

    def test_put_without_metric_carries_over(self):
        american = TIERS + [tier(0, None, "flat", 5, "american")]
        plan = make_plan(PlanKind.PERSONAL, user=self.leader)
        make_version(plan, _first(0), american, metric="lead_count", threshold="40.00")
        r = self.send("put", self.smgr, self.url(plan, f"/versions/{month(1)}"), {"tiers": american})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["metric"], r.data["american_threshold_percent"]),
                         ("lead_count", "40.00"))

    def test_put_without_metric_and_no_prior_version_invalid(self):
        plan = make_plan(PlanKind.PERSONAL, user=self.leader)
        r = self.send("put", self.smgr, self.url(plan, f"/versions/{month(1)}"), {"tiers": TIERS})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_patch_metric_alone_invalid(self):
        r = self.send("patch", self.smgr, self.url(self.plan), {"metric": "sales_amount"})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        r = self.send("patch", self.smgr, self.url(self.plan), {})
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_patch_threshold_on_non_lead_metric(self):
        body = {"metric": "deal_count", "american_threshold_percent": "30",
                "effective_from": month(1), "tiers": TIERS + [tier(0, None, "flat", 5, "american")]}
        r = self.send("patch", self.smgr, self.url(self.plan), body)
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_patch_permissions(self):
        body = {"metric": "deal_count", "effective_from": month(1), "tiers": TIERS}
        self.assertEqual(self.send("patch", self.agent, self.url(self.plan), body).status_code, 403)
        self.assertEqual(self.send("patch", self.mmgr, self.url(self.plan), body).status_code, 404)

    def test_patch_keeps_stored_threshold(self):
        plan = make_plan(PlanKind.PERSONAL, user=self.leader)
        american = TIERS + [tier(0, None, "flat", 5, "american")]
        make_version(plan, date.today().replace(day=1), american, threshold="40.00")
        body = {"metric": "lead_count", "effective_from": month(1), "tiers": american}
        r = self.send("patch", self.smgr, self.url(plan), body)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["american_threshold_percent"], "40.00")

    def test_archived_plan_rejects_patch_and_put(self):
        self.plan.is_active = False
        self.plan.save()
        body = {"metric": "deal_count", "effective_from": month(1), "tiers": TIERS}
        r = self.send("patch", self.smgr, self.url(self.plan), body)
        self.assertEqual((r.status_code, r.data["type"]), (400, "archived"))
        r = self.send("put", self.smgr, self.url(self.plan, f"/versions/{month(1)}"), {"tiers": TIERS})
        self.assertEqual((r.status_code, r.data["type"]), (400, "archived"))

    def test_hr_read_only(self):
        r = self.send("get", self.hr, self.url(self.plan))
        self.assertEqual((r.status_code, r.data["can_edit"]), (200, False))
        self.assertFalse(self.send("get", self.hr, PLANS).data[0]["can_edit"])
        body = {"metric": "deal_count", "effective_from": month(1), "tiers": TIERS}
        self.assertEqual(self.send("patch", self.hr, self.url(self.plan), body).status_code, 403)
        url = self.url(self.plan, f"/versions/{month(1)}")
        self.assertEqual(self.send("put", self.hr, url, {"tiers": TIERS}).status_code, 403)

    def test_delete_archives(self):
        r = self.send("delete", self.smgr, self.url(self.plan))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["is_active"])
        self.assertEqual(self.send("get", self.smgr, PLANS).data, [])
        r = self.send("get", self.smgr, PLANS, {"include_archived": "1"})
        self.assertEqual(len(r.data), 1)
        self.assertEqual(self.send("delete", self.agent, self.url(self.plan)).status_code, 403)


class ListTests(PlansBase):
    def setUp(self):
        super().setUp()
        start = date.today().replace(day=1)
        t = [tier(0, None, "flat", 10)]
        self.sales_default = make_plan(PlanKind.PERSONAL, department=self.sales)
        self.mkt_default = make_plan(PlanKind.PERSONAL, department=self.mkt)
        self.agent_plan = make_plan(PlanKind.PERSONAL, user=self.agent)
        self.mkt_user_plan = make_plan(PlanKind.PERSONAL, user=self.mkt_agent)
        self.sales_team_plan = make_plan(PlanKind.TEAM, team=self.sales_team)
        self.mkt_team_plan = make_plan(PlanKind.TEAM, team=self.mkt_team)
        for p in CommissionPlan.objects.all():
            make_version(p, start, t)

    def ids(self, actor, **kw):
        r = self.send("get", actor, PLANS, kw)
        self.assertEqual(r.status_code, 200)
        return {p["uuid"] for p in r.data}

    def u(self, *plans):
        return {str(p.uuid) for p in plans}

    def test_manager_no_cross_department(self):
        self.assertEqual(self.ids(self.smgr), self.u(
            self.sales_default, self.agent_plan, self.sales_team_plan))

    def test_agent_sees_own_default_and_led_team(self):
        self.assertEqual(self.ids(self.agent), self.u(self.sales_default, self.agent_plan))
        self.assertEqual(self.ids(self.leader), self.u(self.sales_default, self.sales_team_plan))

    def test_owner_and_filters(self):
        self.assertEqual(len(self.ids(self.owner)), 6)
        self.assertEqual(self.ids(self.owner, kind="team"), self.u(self.sales_team_plan, self.mkt_team_plan))
        self.assertEqual(self.ids(self.owner, department=str(self.sales.uuid)), self.u(self.sales_default))
        self.assertEqual(self.ids(self.owner, user=str(self.agent.uuid)), self.u(self.agent_plan))
        self.assertEqual(self.ids(self.owner, team=str(self.sales_team.uuid)), self.u(self.sales_team_plan))
        self.assertEqual(self.send("get", self.owner, PLANS, {"kind": "x"}).status_code, 400)
        self.assertEqual(self.send("get", self.owner, PLANS, {"user": "x"}).status_code, 400)

    def test_archived_hidden_unless_requested(self):
        self.sales_default.is_active = False
        self.sales_default.save()
        self.assertNotIn(str(self.sales_default.uuid), self.ids(self.smgr))
        self.assertIn(str(self.sales_default.uuid), self.ids(self.smgr, include_archived="1"))
        self.assertNotIn(str(self.sales_default.uuid), self.ids(self.agent, include_archived="1"))


class PreviewTests(PlansBase):
    def body(self, **over):
        b = {"metric": "lead_count", "tiers": TIERS, "value": 150}
        b.update(over)
        return b

    def test_preview(self):
        r = self.send("post", self.agent, PREVIEW, self.body())
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data, {"amount": "1500.00", "tier_index": 1, "variant": "normal"})

    def test_preview_american(self):
        tiers = TIERS + [tier(0, None, "flat", 77, "american")]
        r = self.send("post", self.agent, PREVIEW, self.body(
            tiers=tiers, american_threshold_percent="40", american_share=45))
        self.assertEqual(r.data, {"amount": "77.00", "tier_index": 0, "variant": "american"})

    def test_preview_below_first_tier(self):
        r = self.send("post", self.agent, PREVIEW, self.body(tiers=[tier(10, None, "flat", 5)], value=3))
        self.assertEqual(r.data, {"amount": "0.00", "tier_index": None, "variant": "normal"})

    def test_invalid_tiers(self):
        r = self.send("post", self.agent, PREVIEW, self.body(tiers=[tier(0, 9, "flat", 1), tier(50, None, "flat", 1)]))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_tiers"))
        self.assertEqual(r.data["errors"][0]["index"], 1)
        r = self.send("post", self.agent, PREVIEW, self.body(
            tiers=[{"min_value": "abc", "kind": "flat", "value": "1"}]))
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid_tiers"))

    def test_invalid_inputs(self):
        for extra in ({"value": "abc"}, {"value": None}, {"value": -1}, {"value": True},
                      {"american_share": "x"}, {"metric": "nope"}, {"tiers": "x"},
                      {"american_threshold_percent": "x"}):
            r = self.send("post", self.agent, PREVIEW, self.body(**extra))
            self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"), extra)
