from unittest import mock

from django.db.models.signals import post_save

from apps.users.models import User, ZKConfig, fp_signal
from apps.users.tests.base import BaseUserTestCase


class FakeConn:
    def __init__(self):
        self.users = []

    def get_users(self):
        return [mock.Mock(uid=10)]

    def set_user(self, uid, name):
        self.users.append((uid, name))

    def disable_device(self):
        pass

    def enable_device(self):
        pass

    def disconnect(self):
        pass


class FpSignalTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        ZKConfig.objects.create(ip="10.0.0.9", port=4370, timeout=5, password="0", force_udp=False,
                                ommit_ping=False, is_default=True, last_uid=0, name="Door")
        post_save.connect(fp_signal, sender=User)
        self.addCleanup(post_save.disconnect, fp_signal, sender=User)

    def make(self, name):
        return User.objects.create_user(username=name, password="x", email=f"{name}@test.com",
                                        project=self.project, department=self.department)

    def test_new_users_get_distinct_fp_ids(self):
        conn = FakeConn()
        with mock.patch("apps.users.models.ZK") as zk:
            zk.return_value.connect.return_value = conn
            a, b = self.make("fpa"), self.make("fpb")
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.fp_id, b.fp_id), ("11", "12"))
        self.assertEqual(conn.users, [(11, "fpa"), (12, "fpb")])
        self.assertEqual(ZKConfig.objects.get(is_default=True).last_uid, 12)

    def test_unreachable_device_still_creates_user(self):
        with mock.patch("apps.users.models.ZK") as zk:
            zk.return_value.connect.side_effect = OSError("unreachable")
            with self.assertLogs("apps.users.models", level="ERROR"):
                user = self.make("fpc")
        user.refresh_from_db()
        self.assertEqual(user.fp_id, "")
