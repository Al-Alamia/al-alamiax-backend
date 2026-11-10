"""Request-scoped "via" context so activity events can record the channel (e.g. MCP)."""
import contextvars
from contextlib import contextmanager

_via = contextvars.ContextVar("activity_via", default=None)


@contextmanager
def via_context(via: str, client: str):
    token = _via.set((via, client))
    try:
        yield
    finally:
        _via.reset(token)


def current_via() -> dict:
    value = _via.get()
    if not value:
        return {}
    return {"via": value[0], "client": value[1]}
