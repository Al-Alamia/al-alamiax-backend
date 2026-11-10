import datetime
import importlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from django.db import transaction

from apps.activity.context import via_context
from apps.mcp_server.errors import ToolError, map_exception

logger = logging.getLogger("apps.mcp_server")

REGISTRY = {}
_loaded = False


@dataclass
class Tool:
    name: str
    title: str
    description: str
    schema: dict
    func: Callable
    read_only: bool
    visible: Callable


def tool(name, *, title, description, schema, read_only=True, visible=None):
    def deco(func):
        if name in REGISTRY:
            raise ValueError("Duplicate tool name: %s" % name)
        REGISTRY[name] = Tool(name=name, title=title, description=description, schema=schema,
                              func=func, read_only=read_only,
                              visible=visible or (lambda user: True))
        return func
    return deco


def load_tools():
    global _loaded
    if not _loaded:
        importlib.import_module("apps.mcp_server.tools")
        _loaded = True


# --- validation ------------------------------------------------------------

_TYPE_NAMES = {"object": "an object", "string": "a string", "integer": "an integer",
               "boolean": "a boolean", "array": "an array"}


def _bad(path, reason):
    return ToolError("%s: %s" % (path, reason), "invalid_arguments")


def _check_type(t, value):
    if t == "object":
        return isinstance(value, dict)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "array":
        return isinstance(value, list)
    return True


def _validate_value(schema, value, path):
    t = schema.get("type")
    if t:
        if not _check_type(t, value):
            raise _bad(path, "must be %s" % _TYPE_NAMES.get(t, t))
    if "enum" in schema and value not in schema["enum"]:
        raise _bad(path, "must be one of %s" % ", ".join(str(e) for e in schema["enum"]))
    if t == "object":
        return _validate_object(schema, value, path)
    if t == "integer":
        if "minimum" in schema and value < schema["minimum"]:
            raise _bad(path, "must be >= %s" % schema["minimum"])
        if "maximum" in schema and value > schema["maximum"]:
            raise _bad(path, "must be <= %s" % schema["maximum"])
    elif t == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise _bad(path, "must be at least %s characters" % schema["minLength"])
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise _bad(path, "must be at most %s characters" % schema["maxLength"])
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise _bad(path, "must match pattern %s" % schema["pattern"])
        fmt = schema.get("format")
        if fmt == "uuid":
            try:
                return uuid.UUID(value)
            except ValueError:
                raise _bad(path, "must be a valid UUID")
        if fmt == "date":
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise _bad(path, "must be a date in YYYY-MM-DD format")
            try:
                return datetime.date.fromisoformat(value)
            except ValueError:
                raise _bad(path, "must be a valid date in YYYY-MM-DD format")
    elif t == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise _bad(path, "must have at least %s items" % schema["minItems"])
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise _bad(path, "must have at most %s items" % schema["maxItems"])
        if schema.get("uniqueItems"):
            seen = []
            for v in value:
                if v in seen:
                    raise _bad(path, "items must be unique")
                seen.append(v)
        item_schema = schema.get("items")
        if item_schema:
            return [_validate_value(item_schema, v, "%s[%d]" % (path, i))
                    for i, v in enumerate(value)]
    return value


def _validate_object(schema, args, path=""):
    props = schema.get("properties", {})
    prefix = path + "." if path else ""
    for key in args:
        if key not in props:
            raise _bad(prefix + key, "unknown argument")
    out = {}
    for key in schema.get("required", []):
        if key not in args:
            raise _bad(prefix + key, "required")
    for key, sub in props.items():
        if key in args:
            out[key] = _validate_value(sub, args[key], prefix + key)
        elif "default" in sub:
            out[key] = sub["default"]
    return out


def validate_args(schema: dict, args) -> dict:
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ToolError("arguments: must be an object", "invalid_arguments")
    return _validate_object(schema, args)


# --- listing ---------------------------------------------------------------

def visible_tools(user):
    load_tools()
    return [t for t in REGISTRY.values() if t.visible(user)]


def tool_descriptor(t: Tool) -> dict:
    if t.read_only:
        annotations = {"readOnlyHint": True}
    else:
        annotations = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}
    return {"name": t.name, "title": t.title, "description": t.description,
            "inputSchema": t.schema, "annotations": annotations}


# --- calling ---------------------------------------------------------------

def _dumps(data) -> str:
    return json.dumps(data, default=str, separators=(",", ":"), ensure_ascii=False)


def _error_result(err: ToolError) -> dict:
    return {"content": [{"type": "text", "text": err.message}],
            "structuredContent": {"error": err.type, "message": err.message},
            "isError": True}


def _execute(t, user, args, client_name):
    with via_context("mcp", client_name):
        if t.read_only:
            return t.func(user, args)
        with transaction.atomic():
            return t.func(user, args)


def call_tool(user, name, args, *, grant=None, client_name="") -> dict:
    load_tools()
    started = time.monotonic()
    error_type = ""
    try:
        t = REGISTRY.get(name)
        if t is None or not t.visible(user):
            raise ToolError("Unknown tool: %s" % name, "unknown_tool")
        clean = validate_args(t.schema, args)
        try:
            summary, data = _execute(t, user, clean, client_name)
        except ToolError:
            raise
        except Exception as exc:
            raise map_exception(exc)
        result = {"content": [{"type": "text", "text": summary + "\n" + _dumps(data)}],
                  "structuredContent": data, "isError": False}
    except ToolError as err:
        error_type = err.type
        result = _error_result(err)
    except Exception:
        logger.exception("Unexpected error in MCP tool %s", name)
        error_type = "internal_error"
        result = _error_result(ToolError("Internal error", "internal_error"))
    if grant is not None:
        _log_call(user, grant, name, args, error_type, started)
    return result


def _log_call(user, grant, name, args, error_type, started):
    from apps.mcp_server.models import McpCallLog
    try:
        raw = _dumps(args if args is not None else {})
        arguments = json.loads(raw) if len(raw) <= 4096 else {"truncated": raw[:4096]}
        McpCallLog.objects.create(
            grant=grant, user=user, tool=name[:100], arguments=arguments,
            ok=not error_type, error_type=error_type[:100],
            duration_ms=int((time.monotonic() - started) * 1000))
    except Exception:
        logger.exception("Failed to write McpCallLog")
