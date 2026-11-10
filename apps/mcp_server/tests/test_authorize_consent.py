from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from apps.activity.models import ActivityEvent
from apps.mcp_server.models import OAuthAuthorizationCode, OAuthClient, OAuthGrant
from apps.mcp_server.oauth.tokens import hash_token

from .base import McpTestCase

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
CONSENT = "/api/mcp/oauth/consent"


class AuthorizeConsentTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self.oc = OAuthClient.objects.create(
            client_id="cid", client_name="Claude", redirect_uris=[REDIRECT])

    def params(self, **over):
        p = {"response_type": "code", "client_id": "cid", "redirect_uri": REDIRECT,
             "code_challenge": "abc", "code_challenge_method": "S256", "state": "st1"}
        p.update(over)
        return {k: v for k, v in p.items() if v is not None}

    def authorize(self, **over):
        return self.client.get("/oauth/authorize", self.params(**over))

    def make_request(self, **over):
        r = self.authorize(**over)
        self.assertEqual(r.status_code, 302, r.content)
        return parse_qs(urlparse(r["Location"]).query)["request"][0]

    def test_authorize_redirects_to_consent(self):
        r = self.authorize(resource="http://testserver/mcp")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("http://testserver/oauth/consent?request="))
        row = OAuthAuthorizationCode.objects.get()
        self.assertEqual(row.state, "st1")
        self.assertEqual(row.resource, "http://testserver/mcp")
        self.assertIsNone(row.user)

    def test_authorize_bad_client_400_no_redirect(self):
        r = self.authorize(client_id="nope")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("Location", r)

    def test_authorize_redirect_mismatch_400(self):
        r = self.authorize(redirect_uri=REDIRECT + "/")
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("Location", r)

    def test_authorize_requires_s256(self):
        for over in ({"code_challenge_method": None}, {"code_challenge_method": "plain"},
                     {"code_challenge": None}):
            r = self.authorize(**over)
            self.assertEqual(r.status_code, 302)
            q = parse_qs(urlparse(r["Location"]).query)
            self.assertTrue(r["Location"].startswith(REDIRECT))
            self.assertEqual(q["error"], ["invalid_request"])
            self.assertEqual(q["state"], ["st1"])

    def test_authorize_bad_response_type(self):
        r = self.authorize(response_type="token")
        self.assertEqual(parse_qs(urlparse(r["Location"]).query)["error"], ["unsupported_response_type"])

    def test_authorize_wrong_resource(self):
        r = self.authorize(resource="https://evil.example/mcp")
        self.assertTrue(r["Location"].startswith(REDIRECT))
        self.assertEqual(parse_qs(urlparse(r["Location"]).query)["error"], ["invalid_target"])

    def test_consent_requires_auth(self):
        rid = self.make_request()
        self.assertEqual(self.client.get(CONSENT, {"request": rid}).status_code, 401)

    def test_consent_get_shape(self):
        rid = self.make_request()
        self.client.force_authenticate(self.manager)
        r = self.client.get(CONSENT, {"request": rid})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {
            "client_name": "Claude", "redirect_host": "claude.ai",
            "user": {"name": self.manager.get_full_name() or self.manager.username,
                     "role": self.manager.role},
            "eligible": True})

    def test_consent_approve_returns_code_redirect(self):
        rid = self.make_request()
        self.client.force_authenticate(self.manager)
        r = self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json")
        self.assertEqual(r.status_code, 200)
        url = urlparse(r.json()["redirect_to"])
        q = parse_qs(url.query)
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", REDIRECT)
        code = q["code"][0]
        self.assertTrue(code.startswith("amx_ac_"))
        self.assertEqual(q["state"], ["st1"])
        row = OAuthAuthorizationCode.objects.get(request_id=rid)
        self.assertEqual(row.code_hash, hash_token(code))
        self.assertEqual(row.user, self.manager)
        grant = OAuthGrant.objects.get(user=self.manager, client=self.oc)
        ev = ActivityEvent.objects.get(verb="mcp.grant_created")
        self.assertEqual(ev.actor, self.manager)
        self.assertEqual(ev.target_uuid, grant.pk)
        self.assertEqual(ev.target_label, "Claude")

    def test_approve_reuses_active_grant_no_event(self):
        grant = OAuthGrant.objects.create(user=self.manager, client=self.oc)
        rid = self.make_request()
        self.client.force_authenticate(self.manager)
        self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json")
        self.assertEqual(OAuthGrant.objects.filter(user=self.manager).count(), 1)
        self.assertTrue(OAuthGrant.objects.filter(pk=grant.pk).exists())
        self.assertFalse(ActivityEvent.objects.filter(verb="mcp.grant_created").exists())

    def test_redirect_preserves_query_and_omits_empty_state(self):
        self.oc.redirect_uris = [REDIRECT + "?a=1"]
        self.oc.save()
        rid = self.make_request(redirect_uri=REDIRECT + "?a=1", state=None)
        self.client.force_authenticate(self.manager)
        r = self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json")
        q = parse_qs(urlparse(r.json()["redirect_to"]).query)
        self.assertEqual(q["a"], ["1"])
        self.assertIn("code", q)
        self.assertNotIn("state", q)

    def test_consent_deny(self):
        rid = self.make_request()
        self.client.force_authenticate(self.manager)
        r = self.client.post(CONSENT, {"request": rid, "decision": "deny"}, format="json")
        q = parse_qs(urlparse(r.json()["redirect_to"]).query)
        self.assertEqual(q["error"], ["access_denied"])
        self.assertEqual(q["state"], ["st1"])
        self.assertIsNotNone(OAuthAuthorizationCode.objects.get(request_id=rid).used_at)
        self.assertFalse(OAuthGrant.objects.exists())

    def test_consent_bad_decision_400(self):
        rid = self.make_request()
        self.client.force_authenticate(self.manager)
        r = self.client.post(CONSENT, {"request": rid, "decision": "maybe"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_consent_agent_403_not_eligible(self):
        rid = self.make_request()
        self.client.force_authenticate(self.agent)
        for r in (self.client.get(CONSENT, {"request": rid}),
                  self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json")):
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.json(), {"type": "not_eligible",
                                        "message": "Your role can't connect AI apps."})
        self.assertFalse(OAuthGrant.objects.exists())

    def test_consent_expired_404(self):
        rid = self.make_request()
        OAuthAuthorizationCode.objects.update(expires_at=datetime.now() - timedelta(seconds=1))
        self.client.force_authenticate(self.manager)
        for r in (self.client.get(CONSENT, {"request": rid}),
                  self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json")):
            self.assertEqual(r.status_code, 404)
            self.assertEqual(r.json()["type"], "not_found")

    def test_consent_unknown_404(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get(CONSENT, {"request": "zzz"}).status_code, 404)

    def test_consent_reuse_404(self):
        rid = self.make_request()
        self.client.force_authenticate(self.manager)
        body = {"request": rid, "decision": "approve"}
        self.assertEqual(self.client.post(CONSENT, body, format="json").status_code, 200)
        self.assertEqual(self.client.post(CONSENT, body, format="json").status_code, 404)
        self.assertEqual(self.client.get(CONSENT, {"request": rid}).status_code, 404)
        self.assertEqual(OAuthAuthorizationCode.objects.filter(code_hash__isnull=False).count(), 1)


class ConsentAuthHardeningTests(AuthorizeConsentTests):
    def token(self, user):
        from rest_framework_simplejwt.tokens import AccessToken
        return str(AccessToken.for_user(user))

    def test_header_token_json_works(self):
        rid = self.make_request()
        r = self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json",
                             HTTP_AUTHORIZATION="Bearer " + self.token(self.manager))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(OAuthAuthorizationCode.objects.get(request_id=rid).user, self.manager)

    def test_cookie_only_auth_401(self):
        rid = self.make_request()
        self.client.cookies["Authorization"] = self.token(self.manager)
        self.assertEqual(self.client.get(CONSENT, {"request": rid}).status_code, 401)
        r = self.client.post(CONSENT, {"request": rid, "decision": "approve"}, format="json")
        self.assertEqual(r.status_code, 401)
        self.assertIsNone(OAuthAuthorizationCode.objects.get(request_id=rid).user)

    def test_body_token_auth_401(self):
        rid = self.make_request()
        r = self.client.post(CONSENT, {"request": rid, "decision": "approve",
                                       "Authorization": self.token(self.manager)}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_form_encoded_post_415(self):
        rid = self.make_request()
        r = self.client.post(CONSENT, {"request": rid, "decision": "approve"},
                             HTTP_AUTHORIZATION="Bearer " + self.token(self.manager))
        self.assertEqual(r.status_code, 415)
        self.assertIsNone(OAuthAuthorizationCode.objects.get(request_id=rid).user)
