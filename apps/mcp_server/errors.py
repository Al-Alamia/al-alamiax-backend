from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework.exceptions import NotFound as DrfNotFound
from rest_framework.exceptions import PermissionDenied as DrfPermissionDenied
from rest_framework.exceptions import ValidationError as DrfValidationError


class ToolError(Exception):
    def __init__(self, message: str, type: str = "validation"):
        super().__init__(message)
        self.message = message
        self.type = type


def _first_message(detail) -> str:
    if isinstance(detail, dict):
        for key, value in detail.items():
            msg = _first_message(value)
            if msg:
                return "%s: %s" % (key, msg) if key != "non_field_errors" else msg
        return ""
    if isinstance(detail, (list, tuple)):
        for item in detail:
            msg = _first_message(item)
            if msg:
                return msg
        return ""
    return str(detail)


def _django_validation_message(exc) -> str:
    if hasattr(exc, "error_dict"):
        return _first_message({k: [m for e in errs for m in e.messages]
                               for k, errs in exc.error_dict.items()})
    return _first_message(list(exc.messages))


def map_exception(exc) -> ToolError:
    from apps.attendance.services.locks import PeriodClosed
    from apps.users.services.leads import LeadRuleError

    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, (DrfPermissionDenied, DjangoPermissionDenied)):
        msg = str(getattr(exc, "detail", "") or exc) or "Permission denied"
        return ToolError(msg, "forbidden")
    if isinstance(exc, DrfValidationError):
        return ToolError(_first_message(exc.detail) or "Invalid data", "validation")
    if isinstance(exc, DjangoValidationError):
        return ToolError(_django_validation_message(exc) or "Invalid data", "validation")
    if isinstance(exc, (ObjectDoesNotExist, Http404, DrfNotFound)):
        return ToolError("Not found", "not_found")
    if isinstance(exc, PeriodClosed):
        return ToolError(str(exc), "period_closed")
    if isinstance(exc, LeadRuleError):
        return ToolError(str(exc), "validation")
    for attr in ("type", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value:
            return ToolError(str(getattr(exc, "message", None) or str(exc)), value)
    raise exc
