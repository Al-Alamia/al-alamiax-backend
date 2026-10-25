import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from apps.notifications.models import Notification, NotificationRecipient
from apps.notifications.services import notify
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

B = "/api/notifications/"
NOW = datetime(2026, 10, 25, 12, 0)


class InboxApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other = User.objects.create_user(
            username="other", password="pass123", email="other@test.com",
            role=UserTypes.AGENT, project=self.project, department=self.department,
        )
        p = patch("apps.notifications.views._now", return_value=NOW)
        p.start()
        self.addCleanup(p.stop)
        self.authenticate_as(self.agent)

    def _n(self, msg, user=None, **kw):
        return notify([user or self.agent], msg, **kw)

    def test_inbox_only_own_rows_newest_first(self):
        a = self._n("a")
        b = self._n("b")
        self._n("x", self.other)
        Notification.objects.filter(pk=a.pk).update(created_at=NOW - timedelta(hours=2))
        Notification.objects.filter(pk=b.pk).update(created_at=NOW - timedelta(hours=1))
        r = self.client.get(B + "inbox/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 2)
        self.assertEqual([i["message"] for i in r.data["results"]], ["b", "a"])
        self.assertEqual(r.data["results"][0]["uuid"], str(b.pk))

    def test_inbox_hides_retracted_and_marks_expired(self):
        self._n("keep")
        gone = self._n("gone")
        Notification.objects.filter(pk=gone.pk).update(retracted_at=NOW)
        self._n("old", expires_at=NOW - timedelta(hours=1))
        r = self.client.get(B + "inbox/")
        by = {i["message"]: i for i in r.data["results"]}
        self.assertEqual(set(by), {"keep", "old"})
        self.assertTrue(by["old"]["expired"])
        self.assertFalse(by["keep"]["expired"])

    def test_inbox_unread_filter(self):
        self._n("r")
        self._n("u")
        NotificationRecipient.objects.filter(notification__message="r").update(read_at=NOW)
        r = self.client.get(B + "inbox/?unread=1")
        self.assertEqual([i["message"] for i in r.data["results"]], ["u"])

    def test_unread_count_ignores_expired_and_retracted(self):
        self._n("active")
        self._n("expired", expires_at=NOW - timedelta(hours=1))
        ret = self._n("retracted")
        Notification.objects.filter(pk=ret.pk).update(retracted_at=NOW)
        self._n("read")
        NotificationRecipient.objects.filter(notification__message="read").update(read_at=NOW)
        r = self.client.get(B + "unread-count/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"unread": 1})

    def test_read_marks_own_only_and_ignores_unknown(self):
        mine = self._n("mine")
        theirs = self._n("theirs", self.other)
        r = self.client.post(
            B + "read/", {"uuids": [str(mine.pk), str(theirs.pk), str(uuid.uuid4()), "not-a-uuid"]}, format="json"
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"updated": 1})
        self.assertIsNotNone(NotificationRecipient.objects.get(notification=mine).read_at)
        self.assertIsNone(NotificationRecipient.objects.get(notification=theirs).read_at)

    def test_read_invalid_body(self):
        r = self.client.post(B + "read/", {"uuids": "nope"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["type"], "invalid_body")

    def test_read_all(self):
        self._n("a")
        self._n("b")
        self._n("exp", expires_at=NOW - timedelta(hours=1))
        self._n("x", self.other)
        r = self.client.post(B + "read-all/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {"updated": 2})
        self.assertEqual(NotificationRecipient.objects.filter(user=self.other, read_at__isnull=True).count(), 1)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        r = self.client.get(B + "inbox/")
        self.assertIn(r.status_code, (401, 403))
