from datetime import date

from apps.teams.models import CommissionPlan
from apps.teams.serializers import plan_data
from apps.teams.services import personal_version_for, team_versions_for_leader, validate_tiers
from apps.teams.tests.factories import make_plan, make_team, make_version
from apps.teams.tests.test_plans_api import PLANS, TIERS, PlansBase, month, tier
from apps.teams.types import PlanKind

MY = "/api/teams/my"
FLAT = [{"kind": "flat", "min_value": 0, "max_value": None, "value": 1}]


class PlanPerMetricTests(PlansBase):
    def test_two_metrics_same_department(self):
        d = str(self.sales.uuid)
        for metric in ("lead_count", "subscription_count"):
            r = self.post_plan(self.smgr, department=d, metric=metric)
            self.assertEqual((r.status_code, r.data["metric"]), (201, metric), r.data)
        self.assertEqual(CommissionPlan.objects.count(), 2)

    def test_same_department_and_metric_is_duplicate(self):
        d = str(self.sales.uuid)
        self.post_plan(self.smgr, department=d)
        r = self.post_plan(self.smgr, department=d)
        self.assertEqual((r.status_code, r.data["type"]), (400, "duplicate_plan"))

    def test_archived_plan_of_other_metric_not_reactivated(self):
        old = make_plan(PlanKind.PERSONAL, department=self.sales, metric="deal_count")
        old.is_active = False
        old.save()
        r = self.post_plan(self.smgr, department=str(self.sales.uuid))
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotEqual(r.data["uuid"], str(old.uuid))

    def test_patch_metric_rejected(self):
        plan = make_plan(PlanKind.PERSONAL, department=self.sales)
        body = {"metric": "deal_count", "effective_from": month(1), "tiers": TIERS}
        r = self.send("patch", self.smgr, self.url(plan), body)
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))
        plan.refresh_from_db()
        self.assertEqual(plan.metric, "lead_count")

    def test_team_plan_with_american_subscription_metric(self):
        r = self.post_plan(self.smgr, kind="team", team=str(self.sales_team.uuid),
                           metric="american_subscription_count")
        self.assertEqual((r.status_code, r.data["metric"]), (201, "american_subscription_count"), r.data)
        self.assertEqual(r.data["current_version"]["metric"], "american_subscription_count")

    def test_filter_by_metric(self):
        make_plan(PlanKind.PERSONAL, department=self.sales)
        sub = make_plan(PlanKind.PERSONAL, department=self.sales, metric="subscription_count")
        r = self.send("get", self.smgr, PLANS, {"metric": "subscription_count"})
        self.assertEqual([p["uuid"] for p in r.data], [str(sub.uuid)])
        self.assertEqual(self.send("get", self.smgr, PLANS, {"metric": "bogus"}).status_code, 400)

    def test_threshold_only_for_lead_count_plans(self):
        r = self.post_plan(self.smgr, department=str(self.sales.uuid), metric="subscription_count",
                           american_threshold_percent="30",
                           tiers=TIERS + [tier(0, None, "flat", 5, "american")])
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))


class ResolutionTests(PlansBase):
    def test_user_plan_replaces_default_per_metric_only(self):
        dept_lead = make_plan(PlanKind.PERSONAL, department=self.sales)
        dv = make_version(dept_lead, date(2020, 1, 1), FLAT)
        dept_sub = make_plan(PlanKind.PERSONAL, department=self.sales, metric="subscription_count")
        make_version(dept_sub, date(2020, 1, 1), FLAT)
        user_sub = make_plan(PlanKind.PERSONAL, user=self.agent, metric="subscription_count")
        uv = make_version(user_sub, date(2020, 1, 1), FLAT)
        today = date.today()
        self.assertEqual(personal_version_for(self.agent, today, "subscription_count"), uv)
        self.assertEqual(personal_version_for(self.agent, today, "lead_count"), dv)
        self.assertIsNone(personal_version_for(self.agent, today, "deal_count"))

    def test_team_versions_metric_filter(self):
        lead = make_version(make_plan(PlanKind.TEAM, team=self.sales_team), date(2020, 1, 1), FLAT)
        amer = make_version(
            make_plan(PlanKind.TEAM, team=self.sales_team, metric="american_subscription_count"),
            date(2020, 1, 1), FLAT)
        today = date.today()
        all_ = team_versions_for_leader(self.leader, today)
        self.assertEqual({v.pk for _, v in all_}, {lead.pk, amer.pk})
        self.assertEqual(team_versions_for_leader(self.leader, today, "lead_count"),
                         [(self.sales_team, lead)])

    def test_my_lists_one_personal_plan_per_metric(self):
        make_version(make_plan(PlanKind.PERSONAL, department=self.sales), date(2020, 1, 1), FLAT)
        make_version(make_plan(PlanKind.PERSONAL, user=self.agent, metric="subscription_count"),
                     date(2020, 1, 1), FLAT)
        make_version(make_plan(PlanKind.PERSONAL, department=self.sales, metric="subscription_count"),
                     date(2020, 1, 1), FLAT)
        self.authenticate_as(self.agent)
        r = self.client.get(MY)
        self.assertEqual(sorted(p["metric"] for p in r.data["personal_plans"]),
                         ["lead_count", "subscription_count"])
        sub = next(p for p in r.data["personal_plans"] if p["metric"] == "subscription_count")
        self.assertEqual(sub["target"]["type"], "user")

    def test_plan_data_without_version_has_plan_metric(self):
        plan = make_plan(PlanKind.PERSONAL, department=self.sales, metric="sales_american_amount")
        self.assertEqual(plan_data(plan, self.owner, date.today())["metric"], "sales_american_amount")


class AmericanAmountValidationTests(PlansBase):
    def test_sales_american_amount_accepts_cent_contiguous_tiers(self):
        tiers = [{"kind": "percent", "min_value": "0", "max_value": "999.99", "value": "1"},
                 {"kind": "percent", "min_value": "1000.00", "max_value": None, "value": "2"}]
        out = validate_tiers(tiers, "sales_american_amount", None)
        self.assertEqual(len(out), 2)

    def test_subscription_count_requires_whole_bounds(self):
        from apps.teams.services import PlanError
        tiers = [{"kind": "flat", "min_value": "0", "max_value": "9.5", "value": "1"}]
        with self.assertRaises(PlanError):
            validate_tiers(tiers, "subscription_count", None)
