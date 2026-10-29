from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.teams.models import CommissionPlan, PlanVersion
from apps.teams.tests.factories import make_plan, make_team
from apps.teams.types import PlanKind
from apps.users.models import Department, User


class PlanConstraintTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Sales", code="sales")
        self.user = User.objects.create_user(username="u1", password="x", department=self.dept)
        self.team = make_team(self.dept)

    def assert_integrity(self, **kw):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CommissionPlan.objects.create(**kw)

    def test_personal_plan_requires_exactly_one_target(self):
        self.assert_integrity(kind=PlanKind.PERSONAL, department=self.dept, user=self.user)
        self.assert_integrity(kind=PlanKind.PERSONAL)

    def test_team_plan_requires_team_only(self):
        self.assert_integrity(kind=PlanKind.TEAM, team=self.team, department=self.dept)
        self.assert_integrity(kind=PlanKind.TEAM)

    def test_one_plan_per_target(self):
        make_plan(PlanKind.PERSONAL, department=self.dept)
        make_plan(PlanKind.PERSONAL, user=self.user)
        make_plan(PlanKind.TEAM, team=self.team)
        self.assert_integrity(kind=PlanKind.PERSONAL, department=self.dept)
        self.assert_integrity(kind=PlanKind.PERSONAL, user=self.user)
        self.assert_integrity(kind=PlanKind.TEAM, team=self.team)

    def test_version_unique_per_month(self):
        plan = make_plan(PlanKind.PERSONAL, department=self.dept)
        PlanVersion.objects.create(plan=plan, effective_from=date(2026, 11, 1), metric="lead_count")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlanVersion.objects.create(plan=plan, effective_from=date(2026, 11, 1), metric="lead_count")
