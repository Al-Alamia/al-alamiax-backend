from unittest import mock
from datetime import datetime, timedelta

from apps.mcp_server.models import OAuthClient, OAuthGrant, OAuthToken
from apps.mcp_server.oauth.errors import OAuthError
from apps.mcp_server.oauth.tokens import (
    hash_token, issue_pair, resolve_access, revoke_grant, rotate_refresh,
)
from apps.mcp_server.tests.base import McpTestCase


class TokenTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self.client_obj = OAuthClient.objects.create(client_id="c1", redirect_uris=["http://x/cb"])
        self.grant = OAuthGrant.objects.create(user=self.manager, client=self.client_obj)

    def test_issue_and_resolve(self):
        pair = issue_pair(self.grant)
        self.assertEqual(pair["token_type"], "Bearer")
        self.assertEqual(pair["expires_in"], 3600)
        self.assertEqual(pair["scope"], "mcp")
        self.assertTrue(pair["access_token"].startswith("amx_at_"))
        self.assertTrue(pair["refresh_token"].startswith("amx_rt_"))
        tok = resolve_access(pair["access_token"])
        self.assertEqual(tok.grant, self.grant)
        self.assertIsNone(resolve_access(pair["refresh_token"]))
        self.assertIsNone(resolve_access("junk"))

    def test_expired_access_none(self):
        pair = issue_pair(self.grant)
        OAuthToken.objects.filter(kind="access").update(expires_at=datetime.now() - timedelta(seconds=1))
        self.assertIsNone(resolve_access(pair["access_token"]))

    def test_revoked_grant_none(self):
        pair = issue_pair(self.grant)
        revoke_grant(self.grant, by=self.owner)
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)
        self.assertEqual(self.grant.revoked_by, self.owner)
        self.assertIsNone(resolve_access(pair["access_token"]))
        self.assertFalse(OAuthToken.objects.filter(revoked_at__isnull=True).exists())

    def test_second_revoke_keeps_original_revoked_by(self):
        pair = issue_pair(self.grant)
        revoke_grant(self.grant, by=self.owner)
        with self.assertRaises(OAuthError):
            rotate_refresh(pair["refresh_token"], self.client_obj)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.revoked_by, self.owner)

    def test_must_change_password_none(self):
        pair = issue_pair(self.grant)
        self.manager.must_change_password = True
        self.manager.save()
        self.assertIsNone(resolve_access(pair["access_token"]))

    def test_ineligible_user_none(self):
        pair = issue_pair(self.grant)
        self.manager.is_active = False
        self.manager.save()
        self.assertIsNone(resolve_access(pair["access_token"]))

    def test_rotate_refresh_returns_new_pair_and_marks_old_used(self):
        pair = issue_pair(self.grant)
        new = rotate_refresh(pair["refresh_token"], self.client_obj)
        self.assertNotEqual(new["refresh_token"], pair["refresh_token"])
        old = OAuthToken.objects.get(token_hash=hash_token(pair["refresh_token"]))
        self.assertIsNotNone(old.used_at)
        self.assertIsNotNone(resolve_access(new["access_token"]))
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.last_used_at)

    def test_refresh_reuse_revokes_grant(self):
        pair = issue_pair(self.grant)
        new = rotate_refresh(pair["refresh_token"], self.client_obj)
        with self.assertRaises(OAuthError) as cm:
            rotate_refresh(pair["refresh_token"], self.client_obj)
        self.assertEqual(cm.exception.error, "invalid_grant")
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)
        self.assertIsNone(resolve_access(new["access_token"]))

    def test_rotate_rejects_unknown_other_client_expired_ineligible(self):
        pair = issue_pair(self.grant)
        other = OAuthClient.objects.create(client_id="c2")
        for raw, client in [("nope", self.client_obj), (pair["refresh_token"], other),
                            (pair["access_token"], self.client_obj)]:
            with self.assertRaises(OAuthError) as cm:
                rotate_refresh(raw, client)
            self.assertEqual(cm.exception.error, "invalid_grant")
        OAuthToken.objects.filter(kind="refresh").update(expires_at=datetime.now() - timedelta(seconds=1))
        with self.assertRaises(OAuthError):
            rotate_refresh(pair["refresh_token"], self.client_obj)

    def test_stored_hash_only(self):
        pair = issue_pair(self.grant)
        for raw in (pair["access_token"], pair["refresh_token"]):
            self.assertFalse(OAuthToken.objects.filter(token_hash=raw).exists())
            self.assertTrue(OAuthToken.objects.filter(token_hash=hash_token(raw)).exists())

    def test_concurrent_reuse_revokes_grant(self):
        pair = issue_pair(self.grant)
        raw = pair["refresh_token"]

        def race(user):
            # Another request consumes the token after our read, before our CAS.
            OAuthToken.objects.filter(token_hash=hash_token(raw)).update(used_at=datetime.now())
            return True

        with mock.patch("apps.mcp_server.oauth.tokens.is_eligible", side_effect=race):
            with self.assertRaises(OAuthError) as cm:
                rotate_refresh(raw, self.client_obj)
        self.assertEqual(cm.exception.error, "invalid_grant")
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.revoked_at)
        self.assertEqual(OAuthToken.objects.count(), 2)
