import json

from apps.users.admin_permissions import can_view_user, is_top  # noqa: F401  (is_top re-export)
from apps.users.types import UserTypes

MAX_RESULT_BYTES = 100000


def _dumps(data) -> str:
    return json.dumps(data, default=str, separators=(",", ":"), ensure_ascii=False)


def limit_schema() -> dict:
    return {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}


def is_payroll_viewer(user) -> bool:
    return bool(user.is_superuser
                or user.role in {UserTypes.HR, UserTypes.OWNER, UserTypes.MANAGER})


def user_brief(u) -> dict:
    return {
        "uuid": str(u.pk),
        "username": u.username,
        "name": u.get_full_name() or u.username,
        "role": u.role,
        "department": u.department.name if getattr(u, "department_id", None) else None,
    }


def visible_ref(viewer, u, fmt=user_brief):
    """Format a nested user reference, or None when the viewer may not see that user."""
    if u is None or not (u.pk == viewer.pk or can_view_user(viewer, u)):
        return None
    return fmt(u)


def list_result(items, serialize, limit: int) -> dict:
    """Serialize up to ``limit`` items, stopping early when the JSON grows past ~100 KB."""
    items = list(items)
    truncated = len(items) > limit
    out, size = [], 0
    for item in items[:limit]:
        row = serialize(item)
        size += len(_dumps(row).encode("utf-8")) + 1
        if size >= MAX_RESULT_BYTES and out:
            truncated = True
            break
        out.append(row)
    result = {"items": out, "count": len(out), "truncated": truncated}
    if truncated:
        result["hint"] = "narrow the filters"
    return result
