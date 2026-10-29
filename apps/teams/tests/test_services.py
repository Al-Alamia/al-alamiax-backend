from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.notifications.models import Notification, NotificationRecipient
from apps.teams import services
from apps.teams.models import PlanVersion
from apps.teams.services import PlanError
from apps.teams.tests.factories import make_plan, make_team, make_version
from apps.teams.types import PlanKind
from apps.users.models import Department, User

FLAT = [{"min_value": "0", "max_value": None, "kind": "flat", "value": "100"}]
FLAT2 = [{"min_value": "0", "max_value": None, "kind": "flat", "value": "250"}]


def mk_user(name, dept):
    return User.objects.create_user(username=name, password="x", department=dept)


class ResolutionTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Sales", code="sales")
        self.other = Department.objects.create(name="Ops", code="ops")
        self.u = mk_user("u", self.dept)

    def test_month_start(self):
        self.assertEqual(services.month_start(date(2026, 11, 15)), date(2026, 11, 1))

    def test_user_plan_replaces_department_default(self):
        dp = make_plan(PlanKind.PERSONAL, department=self.dept)
        make_version(dp, date(2026, 1, 1), FLAT)
        up = make_plan(PlanKind.PERSONAL, user=self.u)
        uv = make_version(up, date(2026, 1, 1), FLAT)
        self.assertEqual(services.personal_version_for(self.u, date(2026, 3, 9)), uv)

    def test_future_only_user_plan_falls_back_to_department(self):
        dp = make_plan(PlanKind.PERSONAL, department=self.dept)
        dv = make_version(dp, date(2026, 1, 1), FLAT)
        up = make_plan(PlanKind.PERSONAL, user=self.u)
        make_version(up, date(2027, 1, 1), FLAT)
        self.assertEqual(services.personal_version_for(self.u, date(2026, 12, 1)), dv)

    def test_archived_user_plan_ignored(self):
        dp = make_plan(PlanKind.PERSONAL, department=self.dept)
        dv = make_version(dp, date(2026, 1, 1), FLAT)
        up = make_plan(PlanKind.PERSONAL, user=self.u)
        make_version(up, date(2026, 1, 1), FLAT)
        up.is_active = False
        up.save()
        self.assertEqual(services.personal_version_for(self.u, date(2026, 2, 1)), dv)

    def test_no_plans_returns_none(self):
        self.assertIsNone(services.personal_version_for(self.u, date(2026, 2, 1)))

    def test_version_chosen_by_month(self):
        up = make_plan(PlanKind.PERSONAL, user=self.u)
        nov = make_version(up, date(2026, 11, 1), FLAT)
        jan = make_version(up, date(2027, 1, 1), FLAT)
        self.assertEqual(services.personal_version_for(self.u, date(2026, 12, 20)), nov)
        self.assertEqual(services.personal_version_for(self.u, date(2027, 1, 5)), jan)
        self.assertIsNone(services.personal_version_for(self.u, date(2026, 10, 5)))

    def test_team_versions_for_leader(self):
        a = make_team(self.dept, "A", leader=self.u)
        b = make_team(self.dept, "B", leader=self.u)
        c = make_team(self.dept, "C", leader=self.u)
        d = make_team(self.dept, "D", agents=[self.u])
        e = make_team(self.dept, "E", leader=self.u)
        va = make_version(make_plan(PlanKind.TEAM, team=a), date(2026, 1, 1), FLAT)
        vb = make_version(make_plan(PlanKind.TEAM, team=b), date(2026, 1, 1), FLAT)
        make_version(make_plan(PlanKind.TEAM, team=d), date(2026, 1, 1), FLAT)
        make_version(make_plan(PlanKind.TEAM, team=e), date(2026, 1, 1), FLAT)
        e.is_active = False
        e.save()
        self.assertEqual(services.team_versions_for_leader(self.u, date(2026, 5, 1)),
                         [(a, va), (b, vb)])

    def test_team_total(self):
        a, b, lead = (mk_user(n, self.dept) for n in "abl")
        team = make_team(self.dept, leader=lead, agents=[a, b])
        vals = {a.pk: Decimal("10"), b.pk: Decimal("5"), lead.pk: Decimal("7")}
        self.assertEqual(services.team_total(team, vals), Decimal("15"))
        team.include_leader_in_total = True
        self.assertEqual(services.team_total(team, vals), Decimal("22"))
        self.assertEqual(services.team_total(team, {}), Decimal("0"))


class SaveVersionTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Sales", code="sales")
        self.by = mk_user("boss", self.dept)
        self.lead = mk_user("lead", self.dept)
        self.team = make_team(self.dept, leader=self.lead)
        self.plan = make_plan(PlanKind.TEAM, team=self.team)
        self.today = date(2026, 11, 15)

    def test_past_month_rejected(self):
        with self.assertRaises(PlanError) as cm:
            services.save_version(self.plan, date(2026, 10, 1), FLAT, self.by, metric="lead_count", threshold=None, today=self.today)
        self.assertEqual(cm.exception.code, "past_month")

    def test_same_month_replaces_tiers(self):
        services.save_version(self.plan, date(2026, 11, 1), FLAT, self.by, metric="lead_count", threshold=None, today=self.today)
        v = services.save_version(self.plan, date(2026, 11, 20), FLAT2, self.by, metric="lead_count", threshold=None, today=self.today)
        self.assertEqual(PlanVersion.objects.filter(plan=self.plan).count(), 1)
        self.assertEqual([t.value for t in v.tiers.all()], [Decimal("250")])

    def test_future_month_creates_new_version(self):
        services.save_version(self.plan, date(2026, 11, 1), FLAT, self.by, metric="lead_count", threshold=None, today=self.today)
        v = services.save_version(self.plan, date(2026, 12, 1), FLAT2, self.by, metric="lead_count", threshold=None, today=self.today)
        self.assertEqual(v.effective_from, date(2026, 12, 1))
        self.assertEqual(PlanVersion.objects.filter(plan=self.plan).count(), 2)

    def test_team_plan_notifies_leader_once(self):
        services.save_version(self.plan, date(2026, 11, 1), FLAT, self.by, metric="lead_count", threshold=None, today=self.today)
        n = Notification.objects.get()
        self.assertEqual(n.kind, "team")
        self.assertTrue(n.link.startswith("/teams?tab=plans&plan="))
        self.assertEqual(list(NotificationRecipient.objects.values_list("user", flat=True)),
                         [self.lead.pk])

    def test_personal_plan_does_not_notify(self):
        p = make_plan(PlanKind.PERSONAL, department=self.dept)
        services.save_version(p, date(2026, 11, 1), FLAT, self.by, metric="lead_count", threshold=None, today=self.today)
        self.assertEqual(Notification.objects.count(), 0)

    def test_invalid_tiers_leave_db_unchanged(self):
        with self.assertRaises(PlanError) as cm:
            services.save_version(self.plan, date(2026, 11, 1), [], self.by, metric="lead_count", threshold=None, today=self.today)
        self.assertEqual(cm.exception.code, "invalid_tiers")
        self.assertEqual(PlanVersion.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)


class MembershipTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Sales", code="sales")
        self.by = mk_user("boss", self.dept)
        self.lead = mk_user("lead", self.dept)
        self.a, self.b = mk_user("a", self.dept), mk_user("b", self.dept)
        self.team = make_team(self.dept, leader=self.lead)

    def recipients(self):
        return set(NotificationRecipient.objects.values_list("user", flat=True))

    def test_add_notifies_new_agents_only(self):
        services.set_members(self.team, [self.a, self.b], [], self.by)
        self.assertEqual(set(self.team.agents.all()), {self.a, self.b})
        self.assertEqual(self.recipients(), {self.a.pk, self.b.pk})
        self.assertEqual(Notification.objects.get().link, "/teams")
        before = Notification.objects.count()
        services.set_members(self.team, [self.a], [], self.by)
        self.assertEqual(Notification.objects.count(), before)

    def test_adding_leader_rejected(self):
        with self.assertRaises(PlanError) as cm:
            services.set_members(self.team, [self.lead], [], self.by)
        self.assertEqual(cm.exception.code, "leader_is_agent")
        self.assertEqual(self.team.agents.count(), 0)

    def test_remove_keeps_other_teams(self):
        other = make_team(self.dept, "O", agents=[self.b])
        services.set_members(self.team, [self.a, self.b], [], self.by)
        services.set_members(self.team, [], [self.b], self.by)
        self.assertEqual(set(self.team.agents.all()), {self.a})
        self.assertEqual(set(other.agents.all()), {self.b})

    def test_set_leader_removes_from_agents(self):
        self.team.agents.set([self.a, self.b])
        services.set_leader(self.team, self.a, self.by)
        self.team.refresh_from_db()
        self.assertEqual(self.team.leader, self.a)
        self.assertEqual(set(self.team.agents.all()), {self.b})
        services.set_leader(self.team, None, self.by)
        self.team.refresh_from_db()
        self.assertIsNone(self.team.leader)
