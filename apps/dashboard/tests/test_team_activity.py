from datetime import datetime

from apps.activity.models import PageView
from apps.activity.services.events import record_event
from apps.dashboard.registry import build_all
from apps.reports.tests.base import ReportsTestCase
from apps.users.models import User
from apps.users.types import UserTypes

NOW = datetime(2026, 11, 10, 12, 0)


def widgets(user):
    return build_all(user, NOW)["widgets"]


class TeamActivityWidgetTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user(
            username="manager", password="x", email="manager@t.com",
            role=UserTypes.MANAGER, project=self.project, department=self.department)

    def mk(self, name):
        return User.objects.create_user(
            username=name, password="x", email=f"{name}@t.com", role=UserTypes.AGENT,
            project=self.project, department=self.department)

    def test_absent_for_agent(self):
        self.assertNotIn("team_activity", widgets(self.agent))

    def test_manager_counts(self):
        a = self.mk("a")
        b = self.mk("b")
        PageView.objects.create(user=a, path="/x", started_at=datetime(2026, 11, 10, 11, 59),
                                last_seen_at=datetime(2026, 11, 10, 11, 59))
        PageView.objects.create(user=b, path="/x", started_at=datetime(2026, 11, 10, 11, 0),
                                last_seen_at=datetime(2026, 11, 10, 11, 0))
        User.objects.filter(department=self.department).exclude(
            pk__in=[self.manager.pk, a.pk, b.pk]).update(department=None)
        w = widgets(self.manager)["team_activity"]
        self.assertEqual((w["online"], w["total"], w["link"]), (1, 2, "ACTIVITY"))

    def test_latest_capped_5_and_gated(self):
        a = self.mk("a")
        for _ in range(7):
            record_event(a, "request.submitted", subject=a)
        record_event(self.manager, "salary.given", subject=a)
        w = widgets(self.manager)["team_activity"]
        self.assertEqual(len(w["latest"]), 5)
        self.assertNotIn("salary.given", [e["verb"] for e in w["latest"]])
