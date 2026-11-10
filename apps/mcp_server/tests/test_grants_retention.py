import json
import uuid
from datetime import datetime, timedelta

from apps.activity.models import ActivityEvent
from apps.mcp_server import retention
from apps.mcp_server.models import (
    McpCallLog, OAuthAuthorizationCode, OAuthClient, OAuthGrant, OAuthToken)
from apps.mcp_server.oauth.tokens import issue_pair
from apps.mcp_server.tests.base import McpTestCase

GRANTS = "/api/mcp/grants"


class GrantsApiTests(McpTestCase):
    def mk(self, user, name="Claude", cid=None):
        client = OAuthClient.objects.create(
            client_id=cid or "c-%s" % uuid.uuid4().hex[:8], client_name=name)
        return OAuthGrant.objects.create(user=user, client=client)

    def test_list_own(self):
        mine = self.mk(self.manager, "Mine")
        self.mk(self.owner, "Theirs")
        gone = self.mk(self.manager, "Gone")
        gone.revoked_at = datetime.now()
        gone.save()
        self.client.force_authenticate(self.manager)
        r = self.client.get(GRANTS)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([g["uuid"] for g in r.json()], [str(mine.uuid)])
        self.assertEqual(set(r.json()[0]), {"uuid", "client_name", "created_at", "last_used_at"})

    def test_list_other_requires_top(self):
        self.mk(self.manager, "M")
        self.client.force_authenticate(self.hr)
        r = self.client.get(GRANTS, {"user": str(self.manager.uuid)})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["type"], "forbidden")
        self.client.force_authenticate(self.owner)
        r = self.client.get(GRANTS, {"user": str(self.manager.uuid)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)
        self.assertEqual(self.client.get(GRANTS, {"user": "nope"}).status_code, 400)
        self.assertEqual(self.client.get(GRANTS, {"user": str(uuid.uuid4())}).status_code, 404)

    def test_revoke_own_then_mcp_401(self):
        grant = self.mk(self.manager)
        tok = issue_pair(grant)["access_token"]
        msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        post = lambda: self.client.post(  # noqa: E731
            "/mcp", data=msg, content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + tok)
        self.assertEqual(post().status_code, 200)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.delete("%s/%s" % (GRANTS, grant.uuid)).status_code, 204)
        self.assertEqual(post().status_code, 401)
        ev = ActivityEvent.objects.get(verb="mcp.grant_revoked")
        self.assertEqual(ev.actor_id, self.manager.pk)
        self.assertEqual(ev.subject_id, self.manager.pk)
        self.assertEqual(ev.target_label, "Claude")
        # already revoked -> 404
        self.assertEqual(self.client.delete("%s/%s" % (GRANTS, grant.uuid)).status_code, 404)

    def test_owner_revokes_other(self):
        grant = self.mk(self.manager)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.delete("%s/%s" % (GRANTS, grant.uuid)).status_code, 204)
        grant.refresh_from_db()
        self.assertEqual(grant.revoked_by_id, self.owner.pk)
        ev = ActivityEvent.objects.get(verb="mcp.grant_revoked")
        self.assertEqual((ev.actor_id, ev.subject_id), (self.owner.pk, self.manager.pk))

    def test_manager_cannot_revoke_other_404(self):
        grant = self.mk(self.owner)
        self.client.force_authenticate(self.manager)
        r = self.client.delete("%s/%s" % (GRANTS, grant.uuid))
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["type"], "not_found")
        grant.refresh_from_db()
        self.assertIsNone(grant.revoked_at)

    def test_owner_cannot_see_superuser_grants(self):
        grant = self.mk(self.superuser)
        self.client.force_authenticate(self.owner)
        self.assertEqual(
            self.client.get(GRANTS, {"user": str(self.superuser.uuid)}).status_code, 404)
        self.assertEqual(self.client.delete("%s/%s" % (GRANTS, grant.uuid)).status_code, 404)
        grant.refresh_from_db()
        self.assertIsNone(grant.revoked_at)
        self.client.force_authenticate(self.superuser)
        self.assertEqual(len(self.client.get(GRANTS).json()), 1)

    def test_requires_auth(self):
        self.assertEqual(self.client.get(GRANTS).status_code, 401)
        self.assertEqual(self.client.get("/api/mcp/access").status_code, 401)

    def test_access_flag(self):
        self.client.force_authenticate(self.agent)
        r = self.client.get("/api/mcp/access")
        self.assertEqual(r.json(), {"eligible": False, "connector_url": "http://testserver/mcp"})
        self.client.force_authenticate(self.manager)
        self.assertTrue(self.client.get("/api/mcp/access").json()["eligible"])


class RetentionTests(McpTestCase):
    def test_prune_counts(self):
        now = datetime(2026, 11, 10, 12, 0)
        d = lambda days: now - timedelta(days=days)  # noqa: E731

        def client(name, last_used=None, created=None):
            c = OAuthClient.objects.create(client_id=name, client_name=name, last_used_at=last_used)
            if created:
                OAuthClient.objects.filter(pk=c.pk).update(created_at=created)
            return c

        keeper = client("keeper", created=d(100))            # has active grant
        live_grant = OAuthGrant.objects.create(user=self.manager, client=keeper)
        stale = client("stale", created=d(40))               # no grant, old
        client("recent_use", last_used=d(5), created=d(90))  # used recently
        client("new", created=d(1))
        dead = client("dead", created=d(90))
        dead_grant = OAuthGrant.objects.create(
            user=self.agent, client=dead, revoked_at=d(60))
        OAuthToken.objects.create(grant=dead_grant, kind="access", token_hash="h-dead",
                                  expires_at=d(60))

        def code(rid, exp, bound=False):
            return OAuthAuthorizationCode.objects.create(
                request_id=rid, client=keeper, redirect_uri="x", code_challenge="c",
                expires_at=exp, user=self.manager if bound else None,
                code_hash=("h" + rid) if bound else None)
        code("old-unbound", d(2))
        code("old-bound", d(3), bound=True)
        code("fresh", now + timedelta(minutes=5))
        pending = client("pending", created=d(90))
        OAuthAuthorizationCode.objects.create(
            request_id="inflight", client=pending, redirect_uri="x", code_challenge="c",
            expires_at=now + timedelta(minutes=5))
        code("recent-expired", now - timedelta(hours=2))

        def tok(h, exp, revoked=None):
            return OAuthToken.objects.create(
                grant=live_grant, kind="access", token_hash=h, expires_at=exp, revoked_at=revoked)
        tok("t-old-exp", d(8))
        tok("t-old-rev", now + timedelta(days=1), revoked=d(8))
        tok("t-live", now + timedelta(days=1))
        tok("t-recent-exp", d(2))
        OAuthToken.objects.create(
            grant=live_grant, kind="refresh", token_hash="t-rev-refresh",
            expires_at=now + timedelta(days=20), revoked_at=d(8))
        OAuthToken.objects.create(
            grant=live_grant, kind="refresh", token_hash="t-old-refresh",
            expires_at=d(8), revoked_at=d(9))

        def log(created):
            row = McpCallLog.objects.create(user=self.manager, tool="t")
            McpCallLog.objects.filter(pk=row.pk).update(created_at=created)
        log(d(181))
        log(d(10))

        result = retention.prune(now)
        # the dead client's own token is expired >7d, so it counts as a token
        self.assertEqual(result, {"codes": 2, "tokens": 4, "call_logs": 1, "clients": 2})
        self.assertEqual(set(OAuthClient.objects.values_list("client_name", flat=True)),
                         {"keeper", "recent_use", "new", "pending"})
        self.assertEqual(McpCallLog.objects.count(), 1)
        self.assertEqual(set(OAuthToken.objects.values_list("token_hash", flat=True)),
                         {"t-live", "t-recent-exp", "t-rev-refresh"})
        self.assertEqual(OAuthAuthorizationCode.objects.count(), 3)
        self.assertFalse(OAuthGrant.objects.filter(pk=dead_grant.pk).exists())
        self.assertTrue(OAuthGrant.objects.filter(pk=live_grant.pk).exists())
        self.assertFalse(OAuthClient.objects.filter(pk=stale.pk).exists())
