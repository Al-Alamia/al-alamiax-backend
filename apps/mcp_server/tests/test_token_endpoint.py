import base64
import hashlib
import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from apps.mcp_server.models import OAuthAuthorizationCode, OAuthClient, OAuthToken
from apps.mcp_server.oauth.tokens import resolve_access
from apps.users.models import User

from .base import McpTestCase

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
CONSENT = "/api/mcp/oauth/consent"
TOKEN = "/oauth/token"
VERIFIER = "v" * 50


def challenge_for(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class TokenEndpointTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self.oc = OAuthClient.objects.create(
            client_id="cid", client_name="Claude", redirect_uris=[REDIRECT])

    def get_code(self, user=None, resource=None):
        params = {"response_type": "code", "client_id": "cid", "redirect_uri": REDIRECT,
                  "code_challenge": challenge_for(VERIFIER), "code_challenge_method": "S256",
                  "state": "s"}
        if resource:
            params["resource"] = resource
        r = self.client.get("/oauth/authorize", params)
        rid = parse_qs(urlparse(r["Location"]).query)["request"][0]
        self.client.force_authenticate(user or self.manager)
        r = self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json")
        self.client.force_authenticate(None)
        return parse_qs(urlparse(r.json()["redirect_to"]).query)["code"][0]

    def exchange(self, code, **over):
        data = {"grant_type": "authorization_code", "code": code, "client_id": "cid",
                "redirect_uri": REDIRECT, "code_verifier": VERIFIER}
        data.update(over)
        data = {k: v for k, v in data.items() if v is not None}
        return self.client.post(TOKEN, data)

    def test_code_exchange_ok(self):
        r = self.exchange(self.get_code())
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(body["expires_in"], 3600)
        self.assertTrue(body["access_token"].startswith("amx_at_"))
        self.assertTrue(body["refresh_token"].startswith("amx_rt_"))
        self.oc.refresh_from_db()
        self.assertIsNotNone(self.oc.last_used_at)
        self.assertIsNotNone(resolve_access(body["access_token"]))

    def test_json_body_ok(self):
        code = self.get_code()
        r = self.client.post(TOKEN, json.dumps({
            "grant_type": "authorization_code", "code": code, "client_id": "cid",
            "redirect_uri": REDIRECT, "code_verifier": VERIFIER}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_resource_ok_and_mismatch(self):
        code = self.get_code(resource="http://testserver/mcp")
        self.assertEqual(self.exchange(code, resource="http://testserver/mcp").status_code, 200)
        code = self.get_code(resource="http://testserver/mcp")
        r = self.exchange(code, resource="https://evil.example/mcp")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "invalid_grant")

    def assert_error(self, r, error, status=400):
        self.assertEqual(r.status_code, status, r.content)
        self.assertEqual(r.json()["error"], error)

    def test_wrong_verifier_invalid_grant(self):
        self.assert_error(self.exchange(self.get_code(), code_verifier="w" * 50), "invalid_grant")

    def test_short_verifier_invalid_grant(self):
        self.assert_error(self.exchange(self.get_code(), code_verifier="v" * 42), "invalid_grant")

    def test_wrong_redirect_invalid_grant(self):
        self.assert_error(self.exchange(self.get_code(), redirect_uri=REDIRECT + "/x"),
                          "invalid_grant")

    def test_other_client_invalid_grant(self):
        OAuthClient.objects.create(client_id="other", redirect_uris=[REDIRECT])
        self.assert_error(self.exchange(self.get_code(), client_id="other"), "invalid_grant")

    def test_unknown_client_401(self):
        self.assert_error(self.exchange(self.get_code(), client_id="nope"), "invalid_client", 401)

    def test_missing_param_invalid_request(self):
        self.assert_error(self.exchange(self.get_code(), code_verifier=None), "invalid_request")

    def test_unknown_code(self):
        self.assert_error(self.exchange("amx_ac_nope"), "invalid_grant")

    def test_code_reuse_revokes(self):
        code = self.get_code()
        first = self.exchange(code).json()
        self.assertIsNotNone(resolve_access(first["access_token"]))
        self.assert_error(self.exchange(code), "invalid_grant")
        self.assertIsNone(resolve_access(first["access_token"]))
        self.assertFalse(OAuthToken.objects.filter(revoked_at__isnull=True).exists())

    def test_expired_code(self):
        code = self.get_code()
        OAuthAuthorizationCode.objects.update(expires_at=datetime.now() - timedelta(seconds=1))
        self.assert_error(self.exchange(code), "invalid_grant")

    def test_code_exchange_after_role_downgrade(self):
        code = self.get_code()
        User.objects.filter(pk=self.manager.pk).update(role="AGENT")
        self.assert_error(self.exchange(code), "invalid_grant")

    def test_code_exchange_after_grant_revoked(self):
        code = self.get_code()
        from apps.mcp_server.models import OAuthGrant
        OAuthGrant.objects.update(revoked_at=datetime.now())
        self.assert_error(self.exchange(code), "invalid_grant")

    def refresh(self, rt, **over):
        data = {"grant_type": "refresh_token", "refresh_token": rt, "client_id": "cid"}
        data.update(over)
        data = {k: v for k, v in data.items() if v is not None}
        return self.client.post(TOKEN, data)

    def test_refresh_rotation_ok(self):
        first = self.exchange(self.get_code()).json()
        r = self.refresh(first["refresh_token"])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotEqual(r.json()["refresh_token"], first["refresh_token"])

    def test_refresh_requires_client_id(self):
        first = self.exchange(self.get_code()).json()
        self.assert_error(self.refresh(first["refresh_token"], client_id=None), "invalid_request")

    def test_refresh_reuse_revokes_grant(self):
        first = self.exchange(self.get_code()).json()
        second = self.refresh(first["refresh_token"]).json()
        self.assert_error(self.refresh(first["refresh_token"]), "invalid_grant")
        self.assertIsNone(resolve_access(second["access_token"]))
        self.assert_error(self.refresh(second["refresh_token"]), "invalid_grant")

    def test_refresh_after_role_downgrade_invalid_grant(self):
        first = self.exchange(self.get_code()).json()
        User.objects.filter(pk=self.manager.pk).update(role="AGENT")
        self.assert_error(self.refresh(first["refresh_token"]), "invalid_grant")

    def test_unsupported_grant_type(self):
        self.assert_error(self.client.post(TOKEN, {"grant_type": "password"}),
                          "unsupported_grant_type")

    def test_no_store_header(self):
        for r in (self.exchange(self.get_code()), self.exchange("amx_ac_nope"),
                  self.client.post(TOKEN, {"grant_type": "x"})):
            self.assertEqual(r["Cache-Control"], "no-store")
            self.assertEqual(r["Pragma"], "no-cache")

    def test_method_and_preflight(self):
        self.assertEqual(self.client.get(TOKEN).status_code, 405)
        r = self.client.options(TOKEN)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")

    def test_nul_in_client_id_is_4xx(self):
        r = self.client.post(TOKEN, {"grant_type": "refresh_token", "refresh_token": "x",
                                     "client_id": "abc\x00"})
        self.assert_error(r, "invalid_client", 401)
        r = self.client.post(TOKEN, json.dumps({"grant_type": "refresh_token",
                                                "refresh_token": "x", "client_id": "abc\x00"}),
                             content_type="application/json")
        self.assert_error(r, "invalid_client", 401)

    def test_code_reuse_kills_rotated_tokens(self):
        code = self.get_code()
        first = self.exchange(code).json()
        rotated = self.refresh(first["refresh_token"]).json()
        self.assert_error(self.exchange(code), "invalid_grant")
        self.assertIsNone(resolve_access(rotated["access_token"]))
        self.assert_error(self.refresh(rotated["refresh_token"]), "invalid_grant")
