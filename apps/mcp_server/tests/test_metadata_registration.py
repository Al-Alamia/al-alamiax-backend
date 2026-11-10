import json

from django.core.cache import cache
from django.test import TestCase

from apps.mcp_server.models import OAuthClient


class MetadataRegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def post(self, data, **extra):
        body = data if isinstance(data, str) else json.dumps(data)
        return self.client.post("/oauth/register", body, content_type="application/json", **extra)

    def test_protected_resource_metadata(self):
        for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            data = self.client.get(path).json()
            self.assertTrue(data["resource"].endswith("/mcp"))
            self.assertEqual(data["authorization_servers"], [data["resource"][:-4]])
            self.assertEqual(data["scopes_supported"], ["mcp"])

    def test_as_metadata(self):
        data = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(data["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(data["token_endpoint_auth_methods_supported"], ["none"])
        self.assertEqual(data["scopes_supported"], ["mcp"])
        self.assertTrue(data["issuer"] and not data["issuer"].endswith("/"))
        for key, suffix in (("registration_endpoint", "/oauth/register"),
                            ("authorization_endpoint", "/oauth/authorize"),
                            ("token_endpoint", "/oauth/token")):
            self.assertEqual(data[key], data["issuer"] + suffix)

    def test_metadata_cors(self):
        r = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")
        r = self.client.options("/oauth/register")
        self.assertEqual(r.status_code, 204)
        self.assertIn("MCP-Protocol-Version", r["Access-Control-Allow-Headers"])

    def test_register_ok(self):
        r = self.post({"redirect_uris": ["https://claude.ai/cb"], "client_name": "Claude",
                       "unknown": 1, "token_endpoint_auth_method": "none"})
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertTrue(data["client_id"])
        self.assertEqual(data["redirect_uris"], ["https://claude.ai/cb"])
        self.assertEqual(data["token_endpoint_auth_method"], "none")
        self.assertEqual(data["grant_types"], ["authorization_code", "refresh_token"])
        self.assertEqual(data["response_types"], ["code"])
        self.assertIsInstance(data["client_id_issued_at"], int)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")
        self.assertTrue(OAuthClient.objects.filter(client_id=data["client_id"], client_name="Claude").exists())

    def test_register_default_name(self):
        r = self.post({"redirect_uris": ["https://a.com/cb"]})
        self.assertEqual(r.json()["client_name"], "AI client")

    def test_register_rejects(self):
        cases = [
            {},
            {"redirect_uris": []},
            {"redirect_uris": ["http://evil.com/cb"]},
            {"redirect_uris": ["https://a.com/cb#frag"]},
            {"redirect_uris": ["myapp://cb"]},
            {"redirect_uris": ["https://a.com/%d" % i for i in range(11)]},
        ]
        for case in cases:
            r = self.post(case)
            self.assertEqual(r.status_code, 400, case)
            self.assertIn(r.json()["error"], ("invalid_redirect_uri", "invalid_client_metadata"))
            self.assertIn("error_description", r.json())

    def test_register_rejects_tricky_uris(self):
        for uri in ("http://evil.com\\@localhost/cb", "https://evil.com\\@a.com/cb",
                    "https://user@a.com/cb", "https://user:pw@a.com/cb",
                    "http://user@localhost/cb", " https://a.com/cb", "https://a.com/cb ",
                    "https://a.com/c\nb", "https://a.com/c\tb", "http://localhost.evil.com/cb"):
            r = self.post({"redirect_uris": [uri]})
            self.assertEqual(r.status_code, 400, repr(uri))
            self.assertEqual(r.json()["error"], "invalid_redirect_uri")

    def test_register_accepts_uppercase_localhost(self):
        r = self.post({"redirect_uris": ["HTTP://LOCALHOST:8080/cb"]})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["redirect_uris"], ["HTTP://LOCALHOST:8080/cb"])

    def test_register_rejects_bad_metadata(self):
        for body in ("not json", "[1]",
                     {"redirect_uris": ["https://a.com/cb"], "token_endpoint_auth_method": "client_secret_basic"},
                     {"redirect_uris": ["https://a.com/cb"], "client_name": "x" * 101}):
            r = self.post(body)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["error"], "invalid_client_metadata")

    def test_register_allows_localhost(self):
        r = self.post({"redirect_uris": ["http://localhost:6274/cb", "http://127.0.0.1/cb"]})
        self.assertEqual(r.status_code, 201)

    def test_register_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.post({"redirect_uris": ["https://a.com/cb"]}).status_code, 201)
        r = self.post({"redirect_uris": ["https://a.com/cb"]})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json(), {"error": "rate_limited"})
