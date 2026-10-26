import uuid

from rest_framework.test import APIClient

from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

CHANGE = "/api/users/change_password"


def set_url(u):
    return f"/api/users/{u}/set_password"


class ChangePasswordTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.agent)

    def test_success(self):
        res = self.client.post(CHANGE, {"old_password": "pass123", "new_password": "newpass1"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIn("message", res.data)
        self.agent.refresh_from_db()
        self.assertTrue(self.agent.check_password("newpass1"))

    def test_same_password_rejected(self):
        res = self.client.post(CHANGE, {"old_password": "pass123", "new_password": "pass123"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data["type"], "same_password")

    def test_wrong_old(self):
        res = self.client.post(CHANGE, {"old_password": "bad", "new_password": "newpass1"}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("message", res.data)
        self.agent.refresh_from_db()
        self.assertTrue(self.agent.check_password("pass123"))

    def test_short_new(self):
        res = self.client.post(CHANGE, {"old_password": "pass123", "new_password": "12345"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_missing_fields(self):
        res = self.client.post(CHANGE, {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_anonymous(self):
        res = APIClient().post(CHANGE, {"old_password": "pass123", "new_password": "newpass1"}, format="json")
        self.assertEqual(res.status_code, 401)


class SetPasswordTests(BaseUserTestCase):
    def _mk(self, name, role):
        return User.objects.create_user(
            username=name, password="pass123", role=role,
            project=self.project, department=self.department,
        )

    def test_superuser_resets_and_target_can_login(self):
        self.client.force_authenticate(self.superuser)
        res = self.client.post(set_url(self.agent.uuid), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.client.force_authenticate(None)
        login = self.client.post(
            "/api/users/login",
            {"username": "agent", "password": "brandnew", "unique_id": "test-device-id"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)

    def test_reset_blacklists_target_refresh_tokens(self):
        anon = APIClient()
        login = anon.post(
            "/api/users/login",
            {"username": "agent", "password": "pass123", "unique_id": "test-device-id"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        refresh = login.data["refresh"]
        self.client.force_authenticate(self.superuser)
        res = self.client.post(set_url(self.agent.uuid), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 200)
        out = anon.post("/api/users/token/refresh", {"refresh": refresh}, format="json")
        self.assertEqual(out.status_code, 401)

    def test_hr_and_manager_allowed(self):
        for name, role in (("hr1", UserTypes.HR), ("mgr1", UserTypes.MANAGER)):
            u = self._mk(name, role)
            self.client.force_authenticate(u)
            res = self.client.post(set_url(self.agent.uuid), {"new_password": "brandnew"}, format="json")
            self.assertEqual(res.status_code, 200, name)

    def test_agent_forbidden(self):
        self.client.force_authenticate(self.agent)
        res = self.client.post(set_url(self.agent.uuid), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_unknown_uuid(self):
        self.client.force_authenticate(self.superuser)
        res = self.client.post(set_url(uuid.uuid4()), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertIn("message", res.data)

    def test_short_password(self):
        self.client.force_authenticate(self.superuser)
        res = self.client.post(set_url(self.agent.uuid), {"new_password": "12345"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_hr_cannot_reset_superuser(self):
        self.client.force_authenticate(self._mk("hr2", UserTypes.HR))
        res = self.client.post(set_url(self.superuser.uuid), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.superuser.refresh_from_db()
        self.assertFalse(self.superuser.check_password("brandnew"))

    def test_manager_cannot_reset_owner(self):
        owner = self._mk("own1", UserTypes.OWNER)
        self.client.force_authenticate(self._mk("mgr2", UserTypes.MANAGER))
        res = self.client.post(set_url(owner.uuid), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_owner_cannot_reset_superuser(self):
        self.client.force_authenticate(self._mk("own2", UserTypes.OWNER))
        res = self.client.post(set_url(self.superuser.uuid), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_superuser_can_reset_owner(self):
        owner = self._mk("own3", UserTypes.OWNER)
        self.client.force_authenticate(self.superuser)
        res = self.client.post(set_url(owner.uuid), {"new_password": "brandnew"}, format="json")
        self.assertEqual(res.status_code, 200)
