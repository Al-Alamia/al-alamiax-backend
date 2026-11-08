import logging
from typing import Callable, Optional

from .context import DashboardContext, build_context
from .widgets import org, personal, team

logger = logging.getLogger(__name__)

Builder = Callable[[DashboardContext], Optional[dict]]

# Ordered: personal, then team, then organisation.
WIDGETS: "list[tuple[str, Builder]]" = [
    ("attendance_period", personal.build_attendance_period),
    ("my_requests", personal.build_my_requests),
    ("notifications", personal.build_notifications),
    ("my_salary", personal.build_my_salary),
    ("my_reports", personal.build_my_reports),
    ("my_advances", personal.build_my_advances),
    ("team_today", team.build_team_today),
    ("approvals", team.build_approvals),
    ("team_reports", team.build_team_reports),
    ("payroll_period", org.build_payroll_period),
    ("leads", org.build_leads),
    ("treasury", org.build_treasury),
]


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
