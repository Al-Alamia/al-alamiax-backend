from apps.teams.serializers import user_brief


def month_str(d) -> str:
    return f"{d:%Y-%m}"


def salary_entry(entry) -> dict:
    return {
        "uuid": str(entry.uuid),
        "amount": str(entry.amount),
        "effective_from": month_str(entry.effective_from),
        "note": entry.note,
        "created_by": user_brief(entry.created_by) if entry.created_by else None,
        "created_at": entry.created_at.isoformat(),
    }


def rates_data(rates) -> dict:
    return {
        "effective_from": month_str(rates.effective_from),
        "american_lead_price": str(rates.american_lead_price),
        "steps": [{"min_leads": s.min_leads, "amount": str(s.amount)} for s in rates.steps.all()],
    }
