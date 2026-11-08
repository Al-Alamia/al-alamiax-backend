import logging
from typing import Callable, Optional

from .context import DashboardContext, build_context

logger = logging.getLogger(__name__)

Builder = Callable[[DashboardContext], Optional[dict]]

# Ordered: personal, then team, then organisation.
WIDGETS: "list[tuple[str, Builder]]" = []


def build_all(viewer, now) -> dict:
    ctx = build_context(viewer, now)
    widgets = {}
    for key, builder in WIDGETS:
        try:
            payload = builder(ctx)
        except Exception:
            logger.exception("Dashboard widget %r failed", key)
            widgets[key] = {"error": True}
            continue
        if payload is not None:
            widgets[key] = payload
    return {
        "generated_at": now.isoformat(),
        "period": {"key": ctx.period_key, "start": ctx.period_start.isoformat(),
                   "end": ctx.period_end.isoformat()},
        "widgets": widgets,
    }
