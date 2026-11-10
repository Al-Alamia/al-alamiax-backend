import json

from django.test import override_settings

from apps.mcp_server.models import OAuthClient, OAuthGrant
from apps.mcp_server.oauth.tokens import issue_pair
from apps.mcp_server.registry import REGISTRY, tool
from apps.mcp_server.tests.base import McpTestCase
from apps.mcp_server.tools.common import is_top
from apps.users.types import UserTypes

EMPTY = {"type": "object", "properties": {}}
ECHO = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}


class ProtocolTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self._names = ["echo_t7", "top_t7"]
        tool("echo_t7", title="Echo", description="d", schema=ECHO)(
            lambda user, a: ("echoed", {"text": a["text"]}))
        tool("top_t7", title="Top", description="d", schema=EMPTY, visible=is_top)(
            lambda user, a: ("top", {}))

    def tearDown(self):
        for n in self._names:
            REGISTRY.pop(n, None)
        super().tearDown()

    def token_for(self, user):
        client = OAuthClient.objects.create(client_id="c-%s-%s" % (user.username, OAuthClient.objects.count()), client_name="Claude")
        grant = OAuthGrant.objects.create(user=user, client=client)
        self.grant = grant
        return issue_pair(grant)["access_token"]

    def post(self, body, token=None, raw=False, **extra):
        if token:
            extra["HTTP_AUTHORIZATION"] = "Bearer " + token
        data = body if raw else json.dumps(body)
        return self.client.post("/mcp", data=data, content_type="application/json", **extra)

    def rpc(self, user, method, params=None, **kw):
        tok = self.token_for(user)
        msg = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            msg["params"] = params
        return self.post(msg, tok, **kw)

    def test_no_token_401_with_resource_metadata(self):
        r = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "unauthorized"})
        self.assertEqual(r["WWW-Authenticate"],
                         'Bearer resource_metadata="http://testserver/.well-known/oauth-protected-resource/mcp"')

    def test_bad_token_401_invalid_token(self):
        r = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, "nope")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json(), {"error": "invalid_token"})
        self.assertTrue(r["WWW-Authenticate"].endswith(', error="invalid_token"'))

    def test_ineligible_user_401(self):
        tok = self.token_for(self.manager)
        msg = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual(self.post(msg, tok).status_code, 200)
        self.manager.role = UserTypes.AGENT
        self.manager.save()
        self.assertEqual(self.post(msg, tok).status_code, 401)
        self.manager.role = UserTypes.MANAGER
        self.manager.save()
        self.assertEqual(self.post(msg, tok).status_code, 200)
        self.manager.is_active = False
        self.manager.save()
        self.assertEqual(self.post(msg, tok).status_code, 401)

    def test_revoked_grant_401(self):
        tok = self.token_for(self.manager)
        from django.utils import timezone  # noqa
        from datetime import datetime
        OAuthGrant.objects.filter(pk=self.grant.pk).update(revoked_at=datetime.now())
        r = self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, tok)
        self.assertEqual(r.status_code, 401)

    def test_get_405(self):
        r = self.client.get("/mcp")
        self.assertEqual(r.status_code, 405)
        self.assertEqual(r["Allow"], "POST")

    def test_options_preflight(self):
        r = self.client.options("/mcp")
        self.assertEqual(r.status_code, 204)
        self.assertIn("Mcp-Session-Id", r["Access-Control-Allow-Headers"])

    def test_initialize_negotiates(self):
        r = self.rpc(self.manager, "initialize", {"protocolVersion": "2025-03-26"})
        res = r.json()["result"]
        self.assertEqual(res["protocolVersion"], "2025-03-26")
        self.assertEqual(res["serverInfo"], {"name": "al-alamiax", "version": "1.0"})
        self.assertEqual(res["capabilities"], {"tools": {"listChanged": False}})
        self.assertTrue(res["instructions"].startswith("Al-AlamiaX CRM/HR tools."))
        r = self.rpc(self.owner, "initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(r.json()["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(r["Content-Type"], "application/json")

    def test_notification_202(self):
        tok = self.token_for(self.manager)
        r = self.post({"jsonrpc": "2.0", "method": "notifications/initialized"}, tok)
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.content, b"")

    def test_batch(self):
        tok = self.token_for(self.manager)
        r = self.post([{"jsonrpc": "2.0", "id": "a", "method": "ping"},
                       {"jsonrpc": "2.0", "method": "notifications/initialized"},
                       {"jsonrpc": "2.0", "id": 2, "method": "nope"}], tok)
        data = r.json()
        self.assertEqual([d["id"] for d in data], ["a", 2])
        self.assertEqual(data[0]["result"], {})
        self.assertEqual(data[1]["error"]["code"], -32601)

    def test_parse_error(self):
        tok = self.token_for(self.manager)
        r = self.post("{bad", tok, raw=True)
        self.assertEqual(r.json()["error"]["code"], -32700)
        self.assertIsNone(r.json()["id"])

    def test_invalid_request(self):
        tok = self.token_for(self.manager)
        self.assertEqual(self.post({"foo": 1}, tok).json()["error"]["code"], -32600)
        self.assertEqual(self.post([], tok).json()["error"]["code"], -32600)

    def test_unknown_method(self):
        r = self.rpc(self.manager, "foo/bar")
        self.assertEqual(r.json()["error"]["code"], -32601)

    def test_invalid_params(self):
        r = self.rpc(self.manager, "tools/call", {"name": 5})
        self.assertEqual(r.json()["error"]["code"], -32602)
        r = self.rpc(self.manager, "tools/call", [1])
        self.assertEqual(r.json()["error"]["code"], -32602)

    def test_tools_list_filtered_by_role(self):
        def names(u):
            return [t["name"] for t in self.rpc(u, "tools/list").json()["result"]["tools"]]
        self.assertIn("echo_t7", names(self.manager))
        self.assertNotIn("top_t7", names(self.manager))
        self.assertIn("top_t7", names(self.owner))

    def test_tools_call_echo(self):
        r = self.rpc(self.manager, "tools/call", {"name": "echo_t7", "arguments": {"text": "hi"}})
        res = r.json()["result"]
        self.assertFalse(res["isError"])
        self.assertEqual(res["structuredContent"], {"text": "hi"})
        r = self.rpc(self.manager, "tools/call", {"name": "echo_t7", "arguments": "x"})
        self.assertTrue(r.json()["result"]["isError"])

    def test_last_used_at_set(self):
        self.rpc(self.manager, "ping")
        self.grant.refresh_from_db()
        self.assertIsNotNone(self.grant.last_used_at)

    def test_origin_refused(self):
        r = self.rpc(self.manager, "ping", HTTP_ORIGIN="https://evil.com")
        self.assertEqual(r.status_code, 403)

    def test_origin_claude_allowed(self):
        r = self.rpc(self.manager, "ping", HTTP_ORIGIN="https://claude.ai")
        self.assertEqual(r.status_code, 200)
        r = self.rpc(self.owner, "ping", HTTP_ORIGIN="http://testserver")
        self.assertEqual(r.status_code, 200)

    @override_settings(MCP_RATE_LIMIT_PER_MIN=2)
    def test_rate_limit_429(self):
        tok = self.token_for(self.manager)
        msg = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual(self.post(msg, tok).status_code, 200)
        self.assertEqual(self.post(msg, tok).status_code, 200)
        r = self.post(msg, tok)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r["Retry-After"], "60")
        self.assertEqual(r.json(), {"error": "rate_limited"})

    def test_batch_too_large(self):
        tok = self.token_for(self.manager)
        r = self.post([{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(51)], tok)
        self.assertEqual(r.json()["error"]["code"], -32600)

    @override_settings(MCP_RATE_LIMIT_PER_MIN=3)
    def test_batch_counts_against_rate_limit(self):
        tok = self.token_for(self.manager)
        r = self.post([{"jsonrpc": "2.0", "id": i, "method": "ping"} for i in range(4)], tok)
        self.assertEqual(r.status_code, 429)

    def test_deeply_nested_json_is_parse_error(self):
        tok = self.token_for(self.manager)
        r = self.post("[" * 100000, tok, raw=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["error"]["code"], -32700)

    def test_rate_limit_key(self):
        from django.core.cache import cache
        tok = self.token_for(self.manager)
        self.post({"jsonrpc": "2.0", "id": 1, "method": "ping"}, tok)
        self.assertEqual(cache.get("mcp:rl:%s" % self.grant.uuid), 1)
