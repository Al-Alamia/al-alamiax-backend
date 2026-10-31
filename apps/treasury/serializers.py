import datetime as dt

from apps.penalties.serializers import actor_brief


def money(value) -> str:
    return f"{value:.2f}"


def _iso(value):
    if isinstance(value, dt.datetime):
        value = value.date()
    return value.isoformat() if isinstance(value, dt.date) else value


def _ts(value):
    return value.isoformat() if value else None


def group_ref(g):
    return {"id": str(g.uuid), "name": g.name} if g else None


def group_data(g) -> dict:
    return {"id": str(g.uuid), "name": g.name,
            "projects": [{"id": str(p.uuid), "name": p.name} for p in g.projects.order_by("name", "uuid")]}


def entry_data(e) -> dict:
    return {
        "id": str(e.uuid), "direction": e.direction, "category": e.category, "amount": money(e.amount),
        "date": e.date.isoformat(), "details": e.details, "group": group_ref(e.group),
        "advance_id": str(e.advance_id) if e.advance_id else None,
        "import_batch_id": str(e.import_batch_id) if e.import_batch_id else None,
        "reverses_id": str(e.reverses_id) if e.reverses_id else None,
        "reversed_at": _ts(e.reversed_at), "reversal_reason": e.reversal_reason,
        "created_by": actor_brief(e.created_by) if e.created_by else None,
        "created_at": e.created_at.isoformat(),
    }


def batch_data(b) -> dict:
    return {
        "id": str(b.uuid), "row_count": b.row_count, "created_at": b.created_at.isoformat(),
        "created_by": actor_brief(b.created_by) if b.created_by else None,
        "reversed_at": _ts(b.reversed_at), "reversal_reason": b.reversal_reason,
    }


def totals_data(t) -> dict:
    return {k: money(v) for k, v in t.items()}


def row_data(r) -> dict:
    """A clean row (group is a ProjectGroup/None) or a raw parsed row (group is a name string)."""
    g = r.get("group")
    return {"date": _iso(r.get("date")), "amount": money(r["amount"]) if hasattr(r.get("amount"), "quantize")
            else r.get("amount"), "details": r.get("details"), "category": r.get("category"),
            "group": group_ref(g) if hasattr(g, "uuid") else (g or None)}
