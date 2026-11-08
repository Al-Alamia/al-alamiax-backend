from unittest import mock

from apps.dashboard import registry
from apps.users.tests.base import BaseUserTestCase

URL = "/api/dashboard"


def _boom(ctx):
    raise RuntimeError("x")


class EndpointTests(BaseUserTestCase):
    def test_requires_auth(self):
        self.assertEqual(self.client.get(URL).status_code, 401)

    def test_shape(self):
        self.authenticate_as(self.agent)
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"generated_at", "period", "widgets"})
        self.assertEqual(set(r.data["period"]), {"key", "start", "end"})
        self.assertIsInstance(r.data["widgets"], dict)

    def test_trailing_slash_also_works(self):
        self.authenticate_as(self.agent)
        self.assertEqual(self.client.get(URL + "/").status_code, 200)

    def test_failing_builder_isolated(self):
        self.authenticate_as(self.agent)
        widgets = [("ok", lambda c: {"a": 1}), ("boom", _boom), ("hidden", lambda c: None)]
        with mock.patch.object(registry, "WIDGETS", widgets), self.assertLogs(registry.logger, "ERROR"):
            r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["widgets"], {"ok": {"a": 1}, "boom": {"error": True}})
