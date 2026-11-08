def user_ref(user):
    if user is None:
        return None
    return {"uuid": str(user.uuid),
            "name": user.get_full_name().strip() or user.username}


def event_json(e) -> dict:
    return {
        "uuid": str(e.uuid),
        "created_at": e.created_at.isoformat(),
        "verb": e.verb,
        "area": e.area,
        "actor": user_ref(e.actor),
        "subject": user_ref(e.subject),
        "target_type": e.target_type,
        "target_uuid": str(e.target_uuid) if e.target_uuid else None,
        "target_label": e.target_label,
        "data": e.data,
    }
