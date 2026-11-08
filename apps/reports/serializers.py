from .services.submissions import submission_values


def _name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def user_brief(user) -> dict:
    return {"uuid": str(user.uuid), "name": _name(user)}


def definition_data(report_type, active_only=False, used_field_ids=None) -> list:
    """Sections/fields; with used_field_ids, "active or used" (the board rule) instead of all."""
    out = []
    for section in report_type.sections.prefetch_related("fields"):
        if used_field_ids is not None:
            fields = [f for f in section.fields.all()
                      if (section.is_active and f.is_active) or f.pk in used_field_ids]
            if not fields:
                continue
        else:
            if active_only and not section.is_active:
                continue
            fields = [f for f in section.fields.all() if f.is_active or not active_only]
        out.append({
            "uuid": str(section.uuid), "name": section.name, "order": section.order,
            "is_active": section.is_active,
            "fields": [{"uuid": str(f.uuid), "label": f.label, "kind": f.kind, "required": f.required,
                        "order": f.order, "is_active": f.is_active} for f in fields],
        })
    return out


def type_data(rt) -> dict:
    return {
        "uuid": str(rt.uuid), "name": rt.name, "description": rt.description,
        "is_active": rt.is_active, "frequency": rt.frequency,
        "edit_window_days": rt.edit_window_days,
        "departments": [str(d.uuid) for d in rt.departments.all()],
        "excluded_users": [user_brief(u) for u in rt.excluded_users.all()],
        "remind_agents": rt.remind_agents, "remind_at": rt.remind_at.strftime("%H:%M"),
        "digest_leaders": rt.digest_leaders, "order": rt.order,
        "submissions_count": rt.submissions.count(),
        "sections": definition_data(rt),
    }


def submission_data(sub, can_edit: bool, reason) -> dict:
    values = submission_values(sub)
    used = {v for v in sub.values.values_list("field_id", flat=True)}
    return {
        "uuid": str(sub.uuid),
        "report_type": {"uuid": str(sub.report_type.uuid), "name": sub.report_type.name,
                        "frequency": sub.report_type.frequency},
        "user": user_brief(sub.user),
        "period": {"start": sub.period_start.isoformat(), "end": sub.period_end.isoformat()},
        "is_late": sub.is_late, "submitted_at": sub.submitted_at.isoformat(),
        "values": values, "can_edit": can_edit, "reason": reason,
        "sections": definition_data(sub.report_type, used_field_ids=used),
    }
