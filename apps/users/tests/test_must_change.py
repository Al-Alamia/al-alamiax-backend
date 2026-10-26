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
        res = self.client.post("/api/users/change_password", {}, format="json", **auth)
        self.assertEqual(res.status_code, 400)
        self.assertNotIn("password_change_required", res.content.decode())
        res = self.client.post("/api/users/logout", {}, format="json", **auth)
        self.assertEqual(res.status_code, 200)
        res = self.client.post("/api/users/token/refresh", {}, format="json", **auth)
        self.assertEqual(res.status_code, 401)  # refresh token missing, not blocked
        self.assertNotEqual(res.json().get("type"), "password_change_required")
        res = self.client.get("/api/users/me/profile", **auth)  # may 404 until the route exists
        if res.status_code == 403:
            self.assertNotEqual(res.json(), BLOCKED)

    def test_non_allowlisted_post_blocked(self):
        auth = self._auth(self._flag_and_login())
        res = self.client.post("/api/users/project", {"name": "x"}, format="json", **auth)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json(), BLOCKED)

    def test_flagged_user_can_login_with_valid_token(self):
        res = self._flag_and_login()
        token = res.data["Authorization"]
        creds = {"username": "agent", "password": "pass123", "unique_id": "test-device-id"}
        by_header = self.client.post(LOGIN, creds, format="json", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(by_header.status_code, 200)
        self.assertTrue(by_header.data["must_change_password"])
        self.client.cookies["Authorization"] = token
        by_cookie = self.client.post(LOGIN, creds, format="json")
        self.assertEqual(by_cookie.status_code, 200)

    def test_invalid_token_does_not_break_login(self):
        creds = {"username": "agent", "password": "pass123", "unique_id": "test-device-id"}
        res = self.client.post(LOGIN, creds, format="json", HTTP_AUTHORIZATION="Bearer garbage")
        self.assertEqual(res.status_code, 200)

    def test_change_password_clears_flag(self):
        auth = self._auth(self._flag_and_login())
        res = self.client.post("/api/users/change_password",
                               {"old_password": "pass123", "new_password": "newpass1"}, format="json", **auth)
        self.assertEqual(res.status_code, 200)
        self.agent.refresh_from_db()
        self.assertFalse(self.agent.must_change_password)
        self.assertEqual(self.client.get("/api/users/leads/me", **auth).status_code, 200)
