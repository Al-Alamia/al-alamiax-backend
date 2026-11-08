from datetime import datetime, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.activity.models import ActivityEvent, PageView
from apps.activity.services.events import record_event
from apps.activity.services.presence import (
    heartbeat, normalize_path, presence_for, presence_rows,
)
from apps.activity.services.retention import prune
from apps.users.tests.base import BaseUserTestCase

T = datetime(2026, 11, 8, 12, 0, 0)
S = timedelta(seconds=1)


class PresenceTests(BaseUserTestCase):
    def count(self):
        return PageView.objects.filter(user=self.agent).count()

    def test_merge_within_90s(self):
        heartbeat(self.agent, "/a", T)
        heartbeat(self.agent, "/a", T + 90 * S)
        self.assertEqual(self.count(), 1)
        self.assertEqual(PageView.objects.get().last_seen_at, T + 90 * S)

    def test_two_tabs_alternating_paths_two_rows(self):
        for i in range(6):
            heartbeat(self.agent, "/a" if i % 2 == 0 else "/b", T + i * 10 * S)
        self.assertEqual(self.count(), 2)

    def test_split_after_gap(self):
        heartbeat(self.agent, "/a", T)
        heartbeat(self.agent, "/a", T + 91 * S)
        self.assertEqual(self.count(), 2)

    def test_split_on_path_change(self):
        heartbeat(self.agent, "/a", T)
        heartbeat(self.agent, "/b", T + 5 * S)
        self.assertEqual(self.count(), 2)

    def test_strips_query_and_fragment(self):
        self.assertEqual(normalize_path("/leads?x=1#a"), "/leads")
        self.assertEqual(heartbeat(self.agent, "/leads?x=1#a", T).path, "/leads")

    def test_truncates_200(self):
        self.assertEqual(len(normalize_path("/" + "x" * 500)), 200)

    def test_bad_path_raises(self):
        for p in ("", "leads"):
            with self.assertRaises(ValueError):
                heartbeat(self.agent, p, T)

    def test_online_boundary(self):
        now = T
        PageView.objects.create(user=self.agent, path="/a", started_at=now - 200 * S,
                                last_seen_at=now - 120 * S)
        row = presence_for(self.agent, now)
        self.assertTrue(row["online"])
        self.assertEqual(row["current_page"], "/a")
        PageView.objects.update(last_seen_at=now - 121 * S)
        self.assertFalse(presence_for(self.agent, now)["online"])
        row = presence_for(self.superuser, now)
        self.assertFalse(row["online"])
        self.assertIsNone(row["current_page"])
        self.assertIsNone(row["last_seen"])
        self.assertEqual(set(row["user"]), {"uuid", "name", "email", "role"})

    def test_today_seconds(self):
        now = T
        mk = lambda s, d: PageView.objects.create(
            user=self.agent, path="/a", started_at=s, last_seen_at=s + d * S)
        mk(now - timedelta(hours=1), 60)
        mk(now - timedelta(hours=2), 30)
        mk(now - timedelta(days=1), 500)
        self.assertEqual(presence_for(self.agent, now)["today_seconds"], 90)

    def test_rows_sorted(self):
        PageView.objects.create(user=self.agent, path="/a", started_at=T - 1000 * S,
                                last_seen_at=T - 500 * S)
        PageView.objects.create(user=self.superuser, path="/a", started_at=T - 10 * S,
                                last_seen_at=T - 5 * S)
        rows = presence_rows([self.agent, self.superuser], T)
        self.assertTrue(rows[0]["online"])
        self.assertFalse(rows[1]["online"])

    def test_prune_boundaries(self):
        now = T
        keep = PageView.objects.create(user=self.agent, path="/a", started_at=now,
                                       last_seen_at=now - timedelta(days=120))
        PageView.objects.create(user=self.agent, path="/a", started_at=now,
                                last_seen_at=now - timedelta(days=120) - S)
        e_keep = record_event(self.agent, "request.submitted")
        e_old = record_event(self.agent, "request.submitted")
        ActivityEvent.objects.filter(pk=e_keep.pk).update(created_at=now - timedelta(days=365))
        ActivityEvent.objects.filter(pk=e_old.pk).update(created_at=now - timedelta(days=365) - S)
        self.assertEqual(prune(now), (1, 1))
        self.assertEqual(list(PageView.objects.all()), [keep])
        self.assertEqual(list(ActivityEvent.objects.all()), [ActivityEvent.objects.get(pk=e_keep.pk)])

    def test_presence_rows_query_count_constant(self):
        from apps.users.models import User
        from apps.users.types import UserTypes

        def run(users):
            with CaptureQueriesContext(connection) as c:
                presence_rows(users, T)
            return len(c)

        two = [self.agent, self.superuser]
        extra = [User.objects.create_user(
            username=f"u{i}", password="x", email=f"u{i}@t.com", role=UserTypes.AGENT,
            project=self.project, department=self.department) for i in range(3)]
        for u in two + extra:
            heartbeat(u, "/a", T)
        self.assertEqual(run(two), run(two + extra))
