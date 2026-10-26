from apps.users.tests.base import BaseUserTestCase

LOGIN = "/api/users/login"
BLOCKED = {"message": "Password change required", "type": "password_change_required"}


class MustChangeTests(BaseUserTestCase):
    def _flag_and_login(self):
        self.agent.must_change_password = True
        self.agent.save()
        res = self.client.post(
            LOGIN, {"username": "agent", "password": "pass123", "unique_id": "test-device-id"}, format="json")
        self.assertEqual(res.status_code, 200)
        return res

    def _auth(self, res):
        return {"HTTP_AUTHORIZATION": f"Bearer {res.data['Authorization']}"}

    def test_set_password_sets_flag(self):
        self.client.force_authenticate(self.superuser)
        res = self.client.post(f"/api/users/{self.agent.uuid}/set_password", {"new_password": "newpass1"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.agent.refresh_from_db()
        self.assertTrue(self.agent.must_change_password)

    def test_login_returns_flag(self):
        self.assertTrue(self._flag_and_login().data["must_change_password"])

    def test_flagged_user_blocked_403(self):
        res = self._flag_and_login()
        blocked = self.client.get("/api/users/leads/me", **self._auth(res))
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json(), BLOCKED)

    def test_unflagged_user_not_blocked(self):
        res = self.client.post(
            LOGIN, {"username": "agent", "password": "pass123", "unique_id": "test-device-id"}, format="json")
        self.assertEqual(self.client.get("/api/users/leads/me", **self._auth(res)).status_code, 200)

    def test_must_change_allowlist(self):
        auth = self._auth(self._flag_and_login())
        for method, path in (("post", "/api/users/change_password"), ("post", "/api/users/logout"),
                             ("post", "/api/users/token/refresh"), ("get", "/api/users/me/profile")):
            res = self.client.post(path, {}, format="json", **auth) if method == "post" \
                else self.client.get(path, **auth)
            if res.status_code == 403:
                self.assertNotEqual(res.json(), BLOCKED, path)

    def test_change_password_clears_flag(self):
        auth = self._auth(self._flag_and_login())
        res = self.client.post("/api/users/change_password",
                               {"old_password": "pass123", "new_password": "newpass1"}, format="json", **auth)
        self.assertEqual(res.status_code, 200)
        self.agent.refresh_from_db()
        self.assertFalse(self.agent.must_change_password)
        self.assertEqual(self.client.get("/api/users/leads/me", **auth).status_code, 200)
