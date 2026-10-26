from apps.notifications.models import Notification
from apps.users.models import Department, FingerPrintID
from apps.users.types import UserTypes
from .base import BaseUserTestCase
from .user_admin_factories import make_device, make_user

PENDING = "/api/users/devices/pending"


class DevicesApiTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.objects.create(name="Other")
        self.hr = make_user("hr1", UserTypes.HR)
        self.owner = make_user("owner1", UserTypes.OWNER)
        self.manager = make_user("mgr1", UserTypes.MANAGER, department=self.department)
        self.outsider = make_user("out1", UserTypes.AGENT, department=self.other_dept)
        self.pending = make_device(self.agent, "pend-1", status="pending")
        self.out_pending = make_device(self.outsider, "pend-2", status="pending")

    def url(self, user):
        return f"/api/users/admin/users/{user.uuid}/devices"

    def test_self_sees_own_devices_read_only(self):
        self.authenticate_as(self.agent)
        r = self.client.get(self.url(self.agent))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 2)
        for d in r.data:
            self.assertEqual(d["can"], {"approve": False, "reject": False, "rename": False, "revoke": False})
            self.assertNotIn("user", d)
        self.assertEqual({"uuid", "name", "unique_id", "status", "user_agent", "last_used_at", "created_at",
                          "decided_by", "decided_at", "can"}, set(r.data[0]))

    def test_hr_sees_flags(self):
        self.authenticate_as(self.hr)
        by_status = {d["status"]: d for d in self.client.get(self.url(self.agent)).data}
        self.assertEqual(by_status["pending"]["can"],
                         {"approve": True, "reject": True, "rename": True, "revoke": True})
        self.assertEqual(by_status["approved"]["can"],
                         {"approve": False, "reject": False, "rename": True, "revoke": True})

    def test_manager_own_department_only(self):
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(self.url(self.agent)).status_code, 200)
        self.assertEqual(self.client.get(self.url(self.outsider)).status_code, 404)

    def test_agent_cannot_view_other_devices(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(self.url(self.outsider)).status_code, 404)

    def test_pending_per_role(self):
        self.authenticate_as(self.agent)
        r = self.client.get(PENDING)
        self.assertEqual((r.status_code, r.data), (200, []))
        self.authenticate_as(self.manager)
        r = self.client.get(PENDING)
        self.assertEqual([d["unique_id"] for d in r.data], ["pend-1"])
        self.assertEqual(r.data[0]["user"]["username"], "agent")
        self.authenticate_as(self.hr)
        self.assertEqual({d["unique_id"] for d in self.client.get(PENDING).data}, {"pend-1", "pend-2"})

    def test_pending_newest_first(self):
        newer = make_device(self.agent, "pend-3", status="pending")
        self.authenticate_as(self.manager)
        self.assertEqual(self.client.get(PENDING).data[0]["uuid"], str(newer.uuid))

    def test_pending_excludes_own_for_non_top(self):
        make_device(self.hr, "hr-pend", status="pending")
        self.authenticate_as(self.hr)
        self.assertNotIn("hr-pend", {d["unique_id"] for d in self.client.get(PENDING).data})

    def test_approve_and_notify(self):
        self.authenticate_as(self.manager)
        r = self.client.post(f"/api/users/devices/{self.pending.uuid}/approve")
        self.assertEqual((r.status_code, r.data["status"]), (200, "approved"))
        self.assertEqual(r.data["decided_by"]["uuid"], str(self.manager.uuid))
        self.assertTrue(Notification.objects.filter(recipients__user=self.agent).exists())

    def test_reject(self):
        self.authenticate_as(self.hr)
        r = self.client.post(f"/api/users/devices/{self.pending.uuid}/reject")
        self.assertEqual((r.status_code, r.data["status"]), (200, "rejected"))

    def test_approve_non_pending_invalid(self):
        self.authenticate_as(self.hr)
        r = self.client.post(f"/api/users/devices/{self.fingerprint.uuid}/approve")
        self.assertEqual((r.status_code, r.data["type"]), (400, "invalid"))

    def test_rename_and_revoke(self):
        self.authenticate_as(self.hr)
        url = f"/api/users/devices/{self.fingerprint.uuid}"
        r = self.client.patch(url, {"name": "Desk"}, format="json")
        self.assertEqual((r.status_code, r.data["name"]), (200, "Desk"))
        self.assertEqual(self.client.patch(url, {"name": " "}, format="json").status_code, 400)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(FingerPrintID.objects.filter(pk=self.fingerprint.pk).exists())

    def test_invisible_device_404(self):
        self.authenticate_as(self.manager)
        for method, url in (("post", f"/api/users/devices/{self.out_pending.uuid}/approve"),
                            ("patch", f"/api/users/devices/{self.out_pending.uuid}"),
                            ("delete", f"/api/users/devices/{self.out_pending.uuid}")):
            r = getattr(self.client, method)(url)
            self.assertEqual((r.status_code, r.data["type"]), (404, "not_found"), url)
        self.out_pending.refresh_from_db()
        self.assertEqual(self.out_pending.status, "pending")

    def test_visible_but_unmanageable_403(self):
        self.authenticate_as(self.agent)
        for method, url in (("post", f"/api/users/devices/{self.pending.uuid}/approve"),
                            ("patch", f"/api/users/devices/{self.pending.uuid}"),
                            ("delete", f"/api/users/devices/{self.pending.uuid}")):
            r = getattr(self.client, method)(url)
            self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"), url)

    def test_manager_cannot_approve_own_device(self):
        own = make_device(self.manager, "m-pend", status="pending")
        self.authenticate_as(self.manager)
        r = self.client.post(f"/api/users/devices/{own.uuid}/approve")
        self.assertEqual((r.status_code, r.data["type"]), (403, "forbidden"))

    def test_old_device_access_route_gone(self):
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.get("/api/users/device-access").status_code, 404)
