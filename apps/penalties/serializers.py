from .permissions import can_void


def user_name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def user_brief(user) -> dict:
    return {"uuid": str(user.uuid), "name": user_name(user), "username": user.username}


def actor_brief(user) -> dict:
    return {"uuid": str(user.uuid), "name": user_name(user)}


def type_data(t) -> dict:
    return {"uuid": str(t.uuid), "name": t.name, "kind": t.kind,
            "default_value": str(t.default_value), "is_active": t.is_active}


def penalty_data(p, viewer) -> dict:
    return {
        "uuid": str(p.uuid),
        "user": user_brief(p.user),
        "penalty_type": {"uuid": str(p.penalty_type.uuid), "name": p.penalty_type.name} if p.penalty_type else None,
        "title": p.title, "description": p.description, "date": p.date.isoformat(),
        "kind": p.kind, "value": str(p.value),
        "created_by": actor_brief(p.created_by), "created_at": p.created_at.isoformat(),
        "voided_at": p.voided_at.isoformat() if p.voided_at else None,
        "voided_by": actor_brief(p.voided_by) if p.voided_by else None,
        "void_reason": p.void_reason,
        "can": {"void": can_void(viewer, p)},
    }
