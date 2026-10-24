from contextlib import contextmanager
from datetime import date, datetime as dt, timedelta
from unittest import mock

from apps.attendance.models import AttendanceDay, AttendanceSettings, Punch
from apps.attendance.services import device_sync, zk_client
from apps.attendance.tests.factories import assign, make_shift
from apps.attendance.types import PunchSource
from apps.users.models import User, ZKConfig
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

B = "/api/attendance/"
NOW = dt(2026, 10, 21, 12, 0, 0)
DAY = dt(2026, 10, 19)  # Monday


def make_device(ip, name="", **kw):
    return ZKConfig.objects.create(ip=ip, port=4370, timeout=5, password="", force_udp=False,
                                   ommit_ping=False, is_default=False, last_uid=0, name=name, **kw)


class FakeDevices:
    """Maps device ip -> list of ZKRecord, or an exception to raise on connect."""

    def __init__(self, by_ip):
        self.by_ip = by_ip

    @contextmanager
    def __call__(self, config):
        data = self.by_ip[config.ip]
        if isinstance(data, Exception):
            raise data

        class Session:
            def get_attendance(self_inner):
                return list(data)

        yield Session()


def rec(user_id, ts):
    return zk_client.ZKRecord(user_id=user_id, timestamp=ts)


class SyncBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.agent.fp_id = "7"
        self.agent.save()
        assign(make_shift(), department=self.department)

    def use(self, by_ip):
        p = mock.patch.object(zk_client, "OPEN_DEVICE", FakeDevices(by_ip))
        p.start()
        self.addCleanup(p.stop)


class SyncAllTests(SyncBase):
    def test_inserts_evaluates_and_dedupes(self):
        dev = make_device("10.0.0.1", name="Door")
        self.use({"10.0.0.1": [rec("7", DAY.replace(hour=9, minute=5)), rec("7", DAY.replace(hour=17, minute=2)),
                               rec("99", DAY.replace(hour=9))]})
        res = device_sync.sync_all(NOW)
        self.assertEqual(res, [{"uuid": str(dev.uuid), "device": "Door", "ok": True, "new_punches": 2,
                                "error": None}])
        self.assertEqual(Punch.objects.filter(device=dev, source=PunchSource.DEVICE).count(), 2)
        day = AttendanceDay.objects.get(user=self.agent, date=DAY.date())
        self.assertEqual(day.status, "PRESENT")
        dev.refresh_from_db()
        self.assertEqual(dev.last_synced_at, NOW)
        self.assertIsNone(AttendanceSettings.get().sync_started_at)
        again = device_sync.sync_all(NOW + timedelta(minutes=5))
        self.assertEqual(again[0]["new_punches"], 0)
        self.assertEqual(Punch.objects.count(), 2)

    def test_name_falls_back_to_ip(self):
        make_device("10.0.0.2")
        self.use({"10.0.0.2": []})
        self.assertEqual(device_sync.sync_all(NOW)[0]["device"], "10.0.0.2")

    def test_old_records_skipped_when_synced_before(self):
        make_device("10.0.0.1", last_synced_at=dt(2026, 10, 20, 12))
        self.use({"10.0.0.1": [rec("7", dt(2026, 10, 10, 9)), rec("7", dt(2026, 10, 19, 13))]})
        self.assertEqual(device_sync.sync_all(NOW)[0]["new_punches"], 1)

    def test_evaluation_failure_rolls_back_the_device(self):
        dev = make_device("10.0.0.1", name="Door")
        self.use({"10.0.0.1": [rec("7", DAY.replace(hour=9, minute=5))]})
        with mock.patch.object(device_sync, "evaluate_and_allow", side_effect=RuntimeError("boom")):
            res = device_sync.sync_all(NOW)
        self.assertFalse(res[0]["ok"])
        self.assertEqual(res[0]["error"], "boom")
        self.assertEqual(Punch.objects.filter(device=dev).count(), 0)
        dev.refresh_from_db()
        self.assertIsNone(dev.last_synced_at)
        # the next sync starts from scratch and completes
        again = device_sync.sync_all(NOW + timedelta(minutes=5))
        self.assertEqual((again[0]["ok"], again[0]["new_punches"]), (True, 1))
        self.assertTrue(AttendanceDay.objects.filter(user=self.agent, date=DAY.date()).exists())

    def test_error_isolated_per_device(self):
        a, b = make_device("10.0.0.1", "A"), make_device("10.0.0.2", "B")
        self.use({"10.0.0.1": OSError("unreachable"), "10.0.0.2": [rec("7", DAY.replace(hour=9))]})
        res = {r["device"]: r for r in device_sync.sync_all(NOW)}
        self.assertFalse(res["A"]["ok"])
        self.assertIn("unreachable", res["A"]["error"])
        self.assertEqual(res["A"]["new_punches"], 0)
        self.assertTrue(res["B"]["ok"])
        self.assertEqual(res["B"]["new_punches"], 1)
        a.refresh_from_db()
        self.assertIsNone(a.last_synced_at)

    def test_lock_held_raises(self):
        s = AttendanceSettings.get()
        s.sync_started_at = NOW
        s.save()
        with self.assertRaises(device_sync.SyncBusy):
            device_sync.sync_all(NOW + timedelta(minutes=9))

    def test_stale_lock_taken_over_and_released_on_error(self):
        s = AttendanceSettings.get()
        s.sync_started_at = NOW - timedelta(minutes=11)
        s.save()
        make_device("10.0.0.1")
        self.use({"10.0.0.1": []})
        with mock.patch.object(device_sync, "ZKConfig") as cfg:
            cfg.objects.order_by.side_effect = RuntimeError("boom")
            with self.assertRaises(RuntimeError):
                device_sync.sync_all(NOW)
        self.assertIsNone(AttendanceSettings.get().sync_started_at)

    def test_acquire_release(self):
        self.assertTrue(device_sync.acquire_lock(NOW))
        self.assertFalse(device_sync.acquire_lock(NOW))
        device_sync.release_lock()
        self.assertTrue(device_sync.acquire_lock(NOW))


class LockReleaseTests(SyncBase):
    def test_release_only_clears_own_lock(self):
        self.assertTrue(device_sync.acquire_lock(NOW))
        takeover = NOW + timedelta(minutes=11)
        self.assertTrue(device_sync.acquire_lock(takeover))
        device_sync.release_lock(NOW)  # the stale run finishing late
        self.assertEqual(AttendanceSettings.get().sync_started_at, takeover)
        device_sync.release_lock(takeover)
        self.assertIsNone(AttendanceSettings.get().sync_started_at)


class SyncApiTests(SyncBase):
    def setUp(self):
        super().setUp()
        p = mock.patch("apps.attendance.views.config._now", return_value=NOW)
        p.start()
        self.addCleanup(p.stop)

    def test_sync_endpoint(self):
        dev = make_device("10.0.0.1", "Door")
        self.use({"10.0.0.1": [rec("7", DAY.replace(hour=9))]})
        self.authenticate_as(self.superuser)
        r = self.client.post(B + "devices/sync")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data, {"results": [{"uuid": str(dev.uuid), "device": "Door", "ok": True,
                                                "new_punches": 1, "error": None}]})

    def test_no_devices(self):
        self.authenticate_as(self.superuser)
        r = self.client.post(B + "devices/sync")
        self.assertEqual((r.status_code, r.data), (200, {"results": []}))

    def test_busy_409(self):
        s = AttendanceSettings.get()
        s.sync_started_at = NOW
        s.save()
        self.authenticate_as(self.superuser)
        r = self.client.post(B + "devices/sync")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["type"], "sync_running")

    def test_agent_forbidden(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.post(B + "devices/sync").status_code, 403)
