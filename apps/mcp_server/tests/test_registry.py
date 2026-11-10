import datetime
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.activity.models import ActivityEvent
from apps.activity.services.events import record_event
from apps.mcp_server import registry
from apps.mcp_server.errors import ToolError
from apps.mcp_server.models import McpCallLog, OAuthClient, OAuthGrant
from apps.mcp_server.registry import REGISTRY, call_tool, tool, validate_args
from apps.mcp_server.tests.base import McpTestCase
from apps.mcp_server.tools.common import limit_schema, list_result, user_brief
from apps.users.models import User

EMPTY = {"type": "object", "properties": {}}


class DomainErr(Exception):
    type = "period_closed"


class RegistryTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self._names = []

    def tearDown(self):
        for n in self._names:
            REGISTRY.pop(n, None)
        super().tearDown()

    def reg(self, name, func, schema=EMPTY, read_only=True, visible=None):
        self._names.append(name)
        tool(name, title=name, description="d", schema=schema, read_only=read_only,
             visible=visible)(func)

    # validation
    def test_validate_required_and_unknown(self):
        schema = {"type": "object", "properties": {"request_uuid": {"type": "string"}},
                  "required": ["request_uuid"]}
        with self.assertRaises(ToolError) as c:
            validate_args(schema, {})
        self.assertEqual(c.exception.type, "invalid_arguments")
        self.assertEqual(c.exception.message, "request_uuid: required")
        with self.assertRaises(ToolError) as c:
            validate_args(schema, {"request_uuid": "x", "foo": 1})
        self.assertEqual(c.exception.message, "foo: unknown argument")
        with self.assertRaises(ToolError):
            validate_args(schema, [])
        self.assertEqual(validate_args(EMPTY, None), {})

    def test_validate_uuid_and_date_parse(self):
        schema = {"type": "object", "properties": {
            "u": {"type": "string", "format": "uuid"},
            "d": {"type": "string", "format": "date"},
            "m": {"type": "string", "pattern": r"\d{4}-\d{2}"}}}
        u = uuid.uuid4()
        out = validate_args(schema, {"u": str(u), "d": "2026-11-10", "m": "2026-11"})
        self.assertEqual(out["u"], u)
        self.assertEqual(out["d"], datetime.date(2026, 11, 10))
        for bad in ({"u": "nope"}, {"d": "2026-13-01"}, {"d": "20261110"}, {"m": "2026-1"}):
            with self.assertRaises(ToolError):
                validate_args(schema, bad)

    def test_validate_enum_bounds_defaults(self):
        schema = {"type": "object", "properties": {
            "limit": limit_schema(),
            "kind": {"type": "string", "enum": ["a", "b"]},
            "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2,
                     "uniqueItems": True},
            "flag": {"type": "boolean"}, "any": {}}}
        self.assertEqual(validate_args(schema, {})["limit"], 25)
        with self.assertRaises(ToolError) as c:
            validate_args(schema, {"limit": 101})
        self.assertEqual(c.exception.message, "limit: must be <= 100")
        for bad in ({"limit": 0}, {"limit": True}, {"limit": "5"}, {"kind": "c"},
                    {"tags": ["a", "b", "c"]}, {"tags": ["a", "a"]}, {"tags": [1]},
                    {"flag": 1}):
            with self.assertRaises(ToolError):
                validate_args(schema, bad)
        self.assertEqual(validate_args(schema, {"any": {"x": 1}})["any"], {"x": 1})

    # calls
    def test_call_ok_result_shape(self):
        self.reg("t_ok", lambda u, a: ("Hello", {"n": 1}))
        r = call_tool(self.manager, "t_ok", {})
        self.assertFalse(r["isError"])
        self.assertEqual(r["structuredContent"], {"n": 1})
        self.assertEqual(r["content"][0]["text"], 'Hello\n{"n":1}')

    def _err(self, exc, name):
        def f(u, a):
            raise exc
        self.reg(name, f)
        return call_tool(self.manager, name, {})

    def test_maps_permission_denied(self):
        r = self._err(PermissionDenied("nope"), "t_perm")
        self.assertTrue(r["isError"])
        self.assertEqual(r["structuredContent"]["error"], "forbidden")

    def test_maps_validation_error(self):
        r = self._err(ValidationError({"amount": ["too big"]}), "t_val")
        self.assertEqual(r["structuredContent"]["error"], "validation")
        self.assertEqual(r["structuredContent"]["message"], "amount: too big")
        r = self._err(DjangoValidationError("bad"), "t_val2")
        self.assertEqual(r["structuredContent"], {"error": "validation", "message": "bad"})
        r = self._err(ValidationError("plain"), "t_val3")
        self.assertEqual(r["structuredContent"]["message"], "plain")

    def test_maps_typed_domain_error(self):
        r = self._err(DomainErr("Period closed"), "t_dom")
        self.assertEqual(r["structuredContent"]["error"], "period_closed")
        self.assertEqual(r["structuredContent"]["message"], "Period closed")

    def test_maps_not_found(self):
        r = self._err(User.DoesNotExist(), "t_nf")
        self.assertEqual(r["structuredContent"]["error"], "not_found")

    def test_internal_error_hidden(self):
        with self.assertLogs("apps.mcp_server", level="ERROR"):
            r = self._err(RuntimeError("secret"), "t_boom")
        self.assertTrue(r["isError"])
        self.assertEqual(r["content"][0]["text"], "Internal error")
        self.assertEqual(r["structuredContent"]["error"], "internal_error")

    def test_unknown_tool(self):
        r = call_tool(self.manager, "nope", {})
        self.assertTrue(r["isError"])
        self.assertEqual(r["structuredContent"]["error"], "unknown_tool")

    def test_invisible_tool_is_unknown(self):
        self.reg("t_hidden", lambda u, a: ("x", {}), visible=lambda u: False)
        self.assertEqual(call_tool(self.manager, "t_hidden", {})["structuredContent"]["error"],
                         "unknown_tool")
        self.assertNotIn("t_hidden", [t.name for t in registry.visible_tools(self.manager)])

    def test_invalid_args_result(self):
        self.reg("t_args", lambda u, a: ("x", {}),
                 schema={"type": "object", "properties": {}, "required": ["q"]})
        r = call_tool(self.manager, "t_args", {})
        self.assertEqual(r["structuredContent"]["error"], "invalid_arguments")

    def test_duplicate_name(self):
        self.reg("t_dup", lambda u, a: ("x", {}))
        with self.assertRaises(ValueError):
            self.reg("t_dup", lambda u, a: ("x", {}))

    def test_descriptor_annotations(self):
        self.reg("t_r", lambda u, a: ("x", {}))
        self.reg("t_w", lambda u, a: ("x", {}), read_only=False)
        self.assertEqual(registry.tool_descriptor(REGISTRY["t_r"])["annotations"],
                         {"readOnlyHint": True})
        d = registry.tool_descriptor(REGISTRY["t_w"])
        self.assertEqual(d["annotations"], {"readOnlyHint": False, "destructiveHint": True,
                                            "idempotentHint": False})
        self.assertEqual(d["inputSchema"], EMPTY)

    def test_write_rolls_back(self):
        def f(u, a):
            User.objects.create_user(username="ghost", password="x")
            raise ToolError("fail", "validation")
        self.reg("t_rb", f, read_only=False)
        r = call_tool(self.manager, "t_rb", {})
        self.assertTrue(r["isError"])
        self.assertFalse(User.objects.filter(username="ghost").exists())

    def test_call_log_written(self):
        client = OAuthClient.objects.create(client_id="c1", client_name="Claude",
                                            redirect_uris=["https://x/cb"])
        grant = OAuthGrant.objects.create(user=self.manager, client=client)
        self.reg("t_log", lambda u, a: ("ok", {}))
        call_tool(self.manager, "t_log", {}, grant=grant, client_name="Claude")
        call_tool(self.manager, "t_log", {"bad": 1}, grant=grant)
        ok, bad = McpCallLog.objects.order_by("created_at")
        self.assertTrue(ok.ok)
        self.assertEqual(ok.error_type, "")
        self.assertIsInstance(ok.duration_ms, int)
        self.assertEqual(ok.tool, "t_log")
        self.assertFalse(bad.ok)
        self.assertEqual(bad.error_type, "invalid_arguments")
        self.assertEqual(bad.arguments, {"bad": 1})

    def test_record_event_gets_via(self):
        def f(u, a):
            record_event(u, "request.approved", data={"k": 1})
            return "ok", {}
        self.reg("t_via", f, read_only=False)
        call_tool(self.manager, "t_via", {}, client_name="Claude")
        ev = ActivityEvent.objects.get(verb="request.approved")
        self.assertEqual(ev.data["via"], "mcp")
        self.assertEqual(ev.data["client"], "Claude")
        self.assertEqual(ev.data["k"], 1)
        record_event(self.manager, "request.approved")
        self.assertNotIn("via", ActivityEvent.objects.order_by("-created_at").first().data)

    def test_list_result_truncates(self):
        r = list_result(list(range(5)), lambda i: {"i": i}, 3)
        self.assertEqual((r["count"], r["truncated"], r["hint"]), (3, True, "narrow the filters"))
        r = list_result(list(range(3)), lambda i: {"i": i}, 3)
        self.assertFalse(r["truncated"])
        self.assertNotIn("hint", r)
        big = list_result(list(range(50)), lambda i: {"s": "x" * 10000}, 50)
        self.assertTrue(big["truncated"])
        self.assertLess(big["count"], 50)

    def test_user_brief(self):
        b = user_brief(self.manager)
        self.assertEqual(b["uuid"], str(self.manager.pk))
        self.assertEqual(b["department"], self.department.name)
