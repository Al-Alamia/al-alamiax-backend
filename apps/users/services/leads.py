from apps.users.models import LeadUpdate


class LeadRuleError(Exception):
    """A lead business rule was violated; surfaced as a 400 `{"message"}`."""


def log_update(lead, by, type: str, from_value: str = "", to_value: str = "", note: str = "") -> LeadUpdate:
    return LeadUpdate.objects.create(
        lead=lead, by=by, type=type, from_value=from_value, to_value=to_value, note=note
    )
