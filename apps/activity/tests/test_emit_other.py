import datetime as dt
from datetime import date

from apps.activity.models import ActivityEvent
from apps.reports.models import ReportSubmission
from apps.reports.services import definition, submissions
from apps.reports.tests.base import ReportsTestCase
from apps.subscriptions import services as sub_svc
from apps.subscriptions.tests.factories import assign, make_lead, marketing_dept, sales_dept
from apps.teams import services as team_svc
from apps.teams.tests.factories import make_plan, make_team
from apps.teams.types import PlanKind
from apps.users.models import User
from apps.users.services import leads as lead_svc
from apps.users.tests.lead_fixtures import LeadPipelineTestCase
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

FLAT = [{"min_value": "0", "max_value": None, "kind": "flat", "value": "100"}]


class EventAssertions:
    def ev(self, verb, actor, subject, area, n=1):
        qs = ActivityEvent.objects.filter(verb=verb)
        self.assertEqual(qs.count(), n, verb)
        e = qs.latest("created_at")
        self.assertEqual((e.actor, e.subject, e.area), (actor, subject, area), verb)
        return e


class LeadEventTests(EventAssertions, LeadPipelineTestCase):
    def test_assign_emits_one_per_lead_and_return_emits(self):
        leads = [self.make_lead(self.mk_agent, name="Ann"), self.make_lead(self.mk_agent, name="Bob")]
        lead_svc.assign_leads(self.manager, leads, self.sales_agent, "sales")
        self.ev("lead.assigned", self.manager, self.sales_agent, "sales", n=2)
        self.assertEqual(
            set(ActivityEvent.objects.filter(verb="lead.assigned").values_list("target_label", flat=True)),
            {"Ann", "Bob"})
        lead_svc.return_lead(self.sales_agent, leads[0], "wrong number")
        e = self.ev("lead.returned", self.sales_agent, self.sales_agent, "sales")
        self.assertEqual(e.data["reason"], "wrong number")


class SubscriptionEventTests(EventAssertions, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        sales = sales_dept()
        self.a = User.objects.create_user(username="s_a", password="x", role=UserTypes.AGENT,
                                          project=None, department=sales)
        self.m = User.objects.create_user(username="m_u", password="x", role=UserTypes.AGENT,
                                          project=None, department=marketing_dept())
        self.lead = make_lead(self.m)
        assign(self.lead, self.a, "sales")
        today = dt.date.today()
        self.body = {"kind": "new", "plan_name": "Gold", "market": "saudi", "currency": "SAR",
                     "total_amount": "1000", "start_date": today.isoformat(),
                     "end_date": (today + dt.timedelta(days=30)).isoformat()}

    def test_subscription_and_payment_lifecycle(self):
        sub = sub_svc.create_subscription(self.a, self.lead, self.body)
        e = self.ev("subscription.created", self.a, self.a, "sales")
        self.assertEqual(e.data["total_amount"], "1000.00")
        sub_svc.update_subscription(self.superuser, sub, {"plan_name": "Silver"})
        self.ev("subscription.updated", self.superuser, self.a, "sales")
        sub_svc.update_subscription(self.superuser, sub, {"plan_name": "Silver"})
        self.assertEqual(ActivityEvent.objects.filter(verb="subscription.updated").count(), 1)  # no-op
        pay = sub_svc.add_payment(self.a, sub, {"amount": "100", "paid_on": dt.date.today().isoformat(),
                                                "method": "cash"})
        e = self.ev("payment.added", self.a, self.a, "sales")
        self.assertEqual(e.data["amount"], "100.00")
        sub_svc.update_payment(self.a, pay, {"amount": "150"})
        self.ev("payment.updated", self.a, self.a, "sales")
        sub_svc.delete_payment(self.a, pay)
        self.ev("payment.deleted", self.a, self.a, "sales")
        sub_svc.cancel_subscription(self.superuser, sub, "changed mind")
        self.ev("subscription.cancelled", self.superuser, self.a, "sales")
        sub2 = sub_svc.create_subscription(self.a, self.lead, self.body)
        sub_svc.delete_subscription(self.superuser, sub2)
        self.ev("subscription.deleted", self.superuser, self.a, "sales")

    def test_subject_none_without_assigned_agent(self):
        lead = make_lead(self.m)
        assign(lead, self.a, "sales", active=False)
        sub_svc.create_subscription(self.superuser, lead, {**self.body, "seller": str(self.a.pk)})
        e = ActivityEvent.objects.get(verb="subscription.created", target_label__startswith=lead.name)
        self.assertIsNone(e.subject)
        self.assertEqual(e.actor, self.superuser)


class TeamEventTests(EventAssertions, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.u1 = User.objects.create_user(username="u1", password="x", department=self.department)
        self.u2 = User.objects.create_user(username="u2", password="x", department=self.department)
        self.lead_u = User.objects.create_user(username="ld", password="x", department=self.department)

    def test_team_events(self):
        team = team_svc.create_team("T1", self.department, None, [], False, self.superuser)
        self.ev("team.created", self.superuser, None, "teams")
        team_svc.set_members(team, [self.u1, self.u2], [], self.superuser)
        e = self.ev("team.members_changed", self.superuser, None, "teams")
        self.assertEqual(e.data, {"added": ["u1", "u2"], "removed": []})
        team_svc.set_members(team, [], [self.u1], self.superuser)
        self.assertEqual(ActivityEvent.objects.filter(verb="team.members_changed").count(), 2)
        team_svc.set_members(team, [self.u2], [], self.superuser)  # no-op
        self.assertEqual(ActivityEvent.objects.filter(verb="team.members_changed").count(), 2)
        team_svc.set_leader(team, self.lead_u, self.superuser)
        self.ev("team.leader_changed", self.superuser, self.lead_u, "teams")
        team_svc.update_team(team, self.superuser, name="T2")
        e = self.ev("team.updated", self.superuser, None, "teams")
        self.assertEqual(e.data["changed"], ["name"])
        team_svc.update_team(team, self.superuser, name="T2")  # no-op
        self.assertEqual(ActivityEvent.objects.filter(verb="team.updated").count(), 1)

    def test_plan_version_saved(self):
        plan = make_plan(PlanKind.PERSONAL, user=self.u1)
        team_svc.save_version(plan, date(2030, 1, 1), FLAT, self.superuser, threshold=None,
                              today=date(2029, 12, 1))
        e = self.ev("plan.version_saved", self.superuser, None, "teams")
        self.assertEqual(e.data["month"], "2030-01-01")


class ReportEventTests(EventAssertions, ReportsTestCase):
    def test_submit_and_definition(self):
        u = User.objects.create_user(username="mk1", password="x", role=UserTypes.AGENT,
                                     department=self.marketing, project=self.project)
        rt = self.make_type("daily", name="Daily")
        fid = str(rt.sections.first().fields.get(label="n").uuid)
        today = date(2026, 11, 8)
        submissions.save_submission(rt, u, today, {fid: "5"}, today)
        e = self.ev("report.submitted", u, u, "reports")
        self.assertIn("Daily", e.target_label)
        self.assertIn("2026-11-08", e.target_label)
        definition.save_definition(rt, [], actor=self.superuser)
        self.ev("report.definition_saved", self.superuser, None, "reports")
        definition.save_definition(rt, [])
        self.assertEqual(ActivityEvent.objects.filter(
            verb="report.definition_saved", actor__isnull=True).count(), 1)
