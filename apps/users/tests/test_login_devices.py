from apps.notifications.models import Notification, NotificationRecipient
from apps.users.models import Department, FingerPrintID
from apps.users.services.devices import (
    DeviceError, approve_device, device_name, reject_device, rename_device, revoke_device)
from apps.users.tests.base import BaseUserTestCase
from apps.users.tests.user_admin_factories import make_device, make_user
from apps.users.types import DeviceStatus, UserTypes

LOGIN = "/api/users/login"
CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


class LoginDeviceTests(BaseUserTestCase):
    def _login(self, unique_id="dev-new", password="pass123", ua=CHROME_WIN, username="agent"):
        body = {"username": username, "password": password}
        if unique_id is not None:
            body["unique_id"] = unique_id
        return self.client.post(LOGIN, body, format="json", HTTP_USER_AGENT=ua)

    def test_approved_device_logs_in_and_sets_last_used(self):
        res = self._login("test-device-id")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["must_change_password"])
        self.fingerprint.refresh_from_db()
        self.assertIsNotNone(self.fingerprint.last_used_at)

    def test_unknown_device_creates_pending_and_notifies(self):
        hr = make_user("hr1", UserTypes.HR)
        mgr = make_user("mgr1", UserTypes.MANAGER, self.department)
        other_mgr = make_user("mgr2", UserTypes.MANAGER, Department.objects.create(name="Other"))
        res = self._login("dev-new")
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data["type"], "device_pending")
        device = FingerPrintID.objects.get(user=self.agent, unique_id="dev-new")
        self.assertEqual(device.status, DeviceStatus.PENDING)
        self.assertEqual(device.name, "Chrome on Windows")
        self.assertEqual(device.user_agent, CHROME_WIN)
        note = Notification.objects.get(kind="device")
        recipients = set(NotificationRecipient.objects.filter(notification=note).values_list("user_id", flat=True))
        self.assertIn(hr.pk, recipients)
        self.assertIn(mgr.pk, recipients)
        self.assertNotIn(other_mgr.pk, recipients)
        self.assertEqual(note.link, f"/users/{self.agent.uuid}#devices")
        self.assertIsNone(note.sender)

    def test_pending_refused(self):
        make_device(self.agent, "p1", "pending")
        res = self._login("p1")
        self.assertEqual((res.status_code, res.data["type"]), (401, "device_pending"))

    def test_rejected_refused(self):
        make_device(self.agent, "r1", "rejected")
        res = self._login("r1")
        self.assertEqual((res.status_code, res.data["type"]), (401, "device_rejected"))

    def test_missing_unique_id_device_required(self):
        for uid in (None, "", "  "):
            res = self._login(uid)
            self.assertEqual((res.status_code, res.data["type"]), (401, "device_required"))

    def test_wrong_password_creates_no_device(self):
        res = self._login("dev-x", password="nope")
        self.assertEqual(res.status_code, 401)
        self.assertFalse(FingerPrintID.objects.filter(unique_id="dev-x").exists())

    def test_fourth_pending_not_created(self):
        for i in range(3):
            make_device(self.agent, f"p{i}", "pending")
        res = self._login("p-new")
        self.assertEqual((res.status_code, res.data["type"]), (401, "device_pending"))
        self.assertFalse(FingerPrintID.objects.filter(unique_id="p-new").exists())

    def test_superuser_bypasses_devices(self):
        res = self._login(None, username="superuser")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["unique_id"], "SuperUser")

    def test_device_name_parsing(self):
        self.assertEqual(device_name(CHROME_WIN), "Chrome on Windows")
        self.assertEqual(device_name(""), "New device")
        self.assertEqual(device_name("Mozilla/5.0 (Windows NT 10.0) Edg/120 Chrome/120"), "Edge on Windows")
        self.assertEqual(device_name("Mozilla/5.0 (Linux; Android 13) Chrome/120"), "Chrome on Android")


class DeviceServiceTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = make_user("hr1", UserTypes.HR)
        self.mgr = make_user("mgr1", UserTypes.MANAGER, self.department)
        self.other_mgr = make_user("mgr2", UserTypes.MANAGER, Department.objects.create(name="Other"))
        self.device = make_device(self.agent, "pend", "pending")

    def _owner_notes(self, message_part):
        return Notification.objects.filter(kind="device", message__contains=message_part)

    def test_approve_sets_fields_and_notifies_owner(self):
        approve_device(self.mgr, self.device)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.APPROVED)
        self.assertEqual(self.device.decided_by, self.mgr)
        self.assertIsNotNone(self.device.decided_at)
        note = self._owner_notes("was approved").get()
        self.assertEqual(note.sender, self.mgr)
        self.assertEqual(note.link, "/profile")

    def test_reject_sets_fields_and_notifies_owner(self):
        reject_device(self.hr, self.device)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.REJECTED)
        self.assertEqual(self.device.decided_by, self.hr)
        self.assertEqual(self._owner_notes("was rejected").count(), 1)

    def test_non_pending_invalid(self):
        for fn in (approve_device, reject_device):
            with self.assertRaises(DeviceError) as ctx:
                fn(self.hr, self.fingerprint)
            self.assertEqual((ctx.exception.type, ctx.exception.status), ("invalid", 400))

    def test_other_department_manager_forbidden(self):
        for fn in (approve_device, reject_device, revoke_device):
            with self.assertRaises(DeviceError) as ctx:
                fn(self.other_mgr, self.device)
            self.assertEqual((ctx.exception.type, ctx.exception.status), ("forbidden", 403))
        with self.assertRaises(DeviceError) as ctx:
            rename_device(self.other_mgr, self.device, "x")
        self.assertEqual(ctx.exception.type, "forbidden")

    def test_revoke_deletes_and_rename(self):
        rename_device(self.hr, self.device, " Laptop ")
        self.device.refresh_from_db()
        self.assertEqual(self.device.name, "Laptop")
        with self.assertRaises(DeviceError):
            rename_device(self.hr, self.device, "  ")
        revoke_device(self.hr, self.device)
        self.assertFalse(FingerPrintID.objects.filter(pk=self.device.pk).exists())
