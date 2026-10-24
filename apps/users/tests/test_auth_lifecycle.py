from rest_framework_simplejwt.tokens import AccessToken

from apps.users.tests.base import BaseUserTestCase

LOGIN = "/api/users/login"
REFRESH = "/api/users/token/refresh"
LOGOUT = "/api/users/logout"
CREDS = {"username": "agent", "password": "pass123", "unique_id": "test-device-id"}


class AuthLifecycleTests(BaseUserTestCase):
    def _login(self):
        return self.client.post(LOGIN, CREDS, format="json")

    def test_login_post_returns_tokens(self):
        res = self._login()
        self.assertEqual(res.status_code, 200)
        for key in ("Authorization", "refresh", "expire"):
            self.assertIn(key, res.data)
        me = self.client.get(
            "/api/users/leads/me",
            HTTP_AUTHORIZATION=f"Bearer {res.data['Authorization']}",
        )
        self.assertEqual(me.status_code, 200)

    def test_login_get_not_allowed(self):
        res = self.client.get(
            f"{LOGIN}?username=agent&password=pass123&unique_id=test-device-id"
        )
        self.assertEqual(res.status_code, 405)

    def test_login_query_credentials_ignored(self):
        res = self.client.post(
            f"{LOGIN}?username=agent&password=pass123&unique_id=test-device-id",
            {},
            format="json",
        )
        self.assertEqual(res.status_code, 401)

    def test_login_wrong_password(self):
        res = self.client.post(LOGIN, {**CREDS, "password": "nope"}, format="json")
        self.assertEqual(res.status_code, 401)
        self.assertIn("message", res.data)

    def test_access_lifetime_one_hour(self):
        token = AccessToken(self._login().data["Authorization"])
        self.assertEqual(token["exp"] - token["iat"], 3600)

    def test_refresh_rotates(self):
        old = self._login().data["refresh"]
        res = self.client.post(REFRESH, {"refresh": old}, format="json")
        self.assertEqual(res.status_code, 200)
        for key in ("Authorization", "refresh", "expire"):
            self.assertIn(key, res.data)
        self.assertNotEqual(res.data["refresh"], old)
        again = self.client.post(REFRESH, {"refresh": old}, format="json")
        self.assertEqual(again.status_code, 401)

    def test_refresh_inactive_user_rejected(self):
        refresh = self._login().data["refresh"]
        self.agent.is_active = False
        self.agent.save()
        res = self.client.post(REFRESH, {"refresh": refresh}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_refresh_garbage(self):
        res = self.client.post(REFRESH, {"refresh": "x"}, format="json")
        self.assertEqual(res.status_code, 401)
        res = self.client.post(REFRESH, {}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_logout_blacklists_refresh(self):
        refresh = self._login().data["refresh"]
        res = self.client.post(LOGOUT, {"refresh": refresh}, format="json")
        self.assertEqual(res.status_code, 200)
        res = self.client.post(REFRESH, {"refresh": refresh}, format="json")
        self.assertEqual(res.status_code, 401)

    def test_logout_without_token_ok(self):
        self.assertEqual(self.client.post(LOGOUT, {}, format="json").status_code, 200)
        self.assertEqual(
            self.client.post(LOGOUT, {"refresh": "x"}, format="json").status_code, 200
        )

    def test_login_with_existing_access_token(self):
        access = self._login().data["Authorization"]
        res = self.client.post(
            LOGIN, {"unique_id": "test-device-id"}, format="json", HTTP_AUTHORIZATION=f"Bearer {access}"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["Authorization"], access)
        self.assertTrue(res.data["refresh"])
