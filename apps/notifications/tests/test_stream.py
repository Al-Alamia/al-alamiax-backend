import json
from datetime import datetime, timedelta
from itertools import islice

from apps.notifications.models import NotificationRecipient
from apps.notifications.services import notify
from apps.notifications.stream import event_stream
from apps.users.tests.base import BaseUserTestCase

URL = "/api/notifications/stream"
T0 = datetime(2026, 10, 25, 12, 0)


class FakeTime:
    def __init__(self, on_sleep=None):
        self.now = T0
        self.calls = 0
        self.on_sleep = on_sleep

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.calls += 1
        self.now += timedelta(seconds=seconds)
        if self.on_sleep:
            self.on_sleep(self.calls)


def parse(frame):
    assert frame.startswith("event: snapshot\ndata: ") and frame.endswith("\n\n"), frame
    return json.loads(frame.split("data: ", 1)[1])


class StreamTests(BaseUserTestCase):
    def test_stream_requires_auth(self):
        r = self.client.get(URL)
        self.assertIn(r.status_code, (401, 403))
        self.assertFalse(r.streaming)

    def test_stream_headers(self):
        self.authenticate_as(self.agent)
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.streaming)
        self.assertEqual(r["Content-Type"], "text/event-stream")
        self.assertEqual(r["Cache-Control"], "no-cache")
        self.assertEqual(r["X-Accel-Buffering"], "no")

    def test_first_frame_is_snapshot(self):
        notify([self.agent], "old")
        n = notify([self.agent], "new")
        ft = FakeTime()
        gen = event_stream(self.agent, T0 + timedelta(hours=1), clock=ft.clock, sleep=ft.sleep)
        data = parse(next(gen))
        self.assertEqual(data["unread"], 2)
        self.assertEqual(data["latest"]["uuid"], str(n.pk))

    def test_sends_snapshot_only_on_change(self):
        notify([self.agent], "first")
        ft = FakeTime(on_sleep=lambda c: notify([self.agent], "new") if c == 2 else None)
        gen = event_stream(self.agent, T0 + timedelta(hours=1), clock=ft.clock, sleep=ft.sleep, poll=3, ping=15)
        frames = list(islice(gen, 4))
        self.assertEqual(parse(frames[0])["unread"], 1)
        self.assertEqual(parse(frames[1])["unread"], 2)
        # no further change: pings only, one per 15 s since the last frame (5 polls of 3 s)
        self.assertEqual(frames[2:], [": ping\n\n", ": ping\n\n"])
        # snapshot at call 2 (t=6s); pings at t=21s and t=36s
        self.assertEqual(ft.now, T0 + timedelta(seconds=36))

    def test_read_elsewhere_emits_snapshot(self):
        notify([self.agent], "a")
        notify([self.agent], "b")
        ft = FakeTime(on_sleep=lambda c: NotificationRecipient.objects.filter(user=self.agent).update(read_at=T0) if c == 1 else None)
        gen = event_stream(self.agent, T0 + timedelta(hours=1), clock=ft.clock, sleep=ft.sleep)
        first, second = islice(gen, 2)
        self.assertEqual(parse(first)["unread"], 2)
        self.assertEqual(parse(second)["unread"], 0)

    def test_stops_at_token_expiry(self):
        ft = FakeTime()
        frames = list(event_stream(self.agent, T0 + timedelta(seconds=10), clock=ft.clock, sleep=ft.sleep))
        self.assertEqual(len(frames), 1)  # initial snapshot, then ends
        self.assertGreaterEqual(ft.now, T0 + timedelta(seconds=10))
