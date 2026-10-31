import re
import uuid as uuid_lib
from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.permissions import is_hr_plus
from apps.attendance.views import error
from apps.users.models import Department, User

from . import services
from .models import RATE_CURRENCIES, BasicSalary, DepartmentRates, ExchangeRate
from .permissions import can_edit_rates, can_edit_salary, can_view_rates, can_view_salary
from .serializers import month_str, rates_data, salary_entry
from .services import ConfigError

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _invalid(message):
    return error(message, "invalid", 400)


def _not_found():
    return error("Not found", "not_found", 404)


def _forbidden():
    return error("You do not have permission to do that.", "forbidden", 403)


def _config_error(e: ConfigError):
    return error(e.message, e.code, 404 if e.code == "not_found" else 400)


def _month(raw):
    m = MONTH_RE.match(raw) if isinstance(raw, str) else None
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def _is_uuid(raw):
    try:
        uuid_lib.UUID(str(raw))
        return True
    except ValueError:
        return False


def _body(request):
    return request.data if isinstance(request.data, dict) else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def salaries(request):
    raw = request.query_params.get("user")
    if raw is None:
        target = request.user
    else:
        target = User.objects.filter(uuid=raw).first() if _is_uuid(raw) else None
        if target is None or not can_view_salary(request.user, target):
            return _not_found()
    entries = list(BasicSalary.objects.filter(user=target).select_related("created_by"))
    today = date.today()
    cur = next((e for e in entries if e.effective_from <= today), None)
    current = ({"amount": str(cur.amount), "effective_from": month_str(cur.effective_from)}
               if cur else None)
    return Response({"current": current, "history": [salary_entry(e) for e in entries]})


@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def salary_detail(request, uuid, month):
    target = User.objects.filter(uuid=uuid).first()
    if target is None or not can_view_salary(request.user, target):
        return _not_found()
    if not can_edit_salary(request.user, target):
        return _forbidden()
    when = _month(month)
    body = _body(request)
    if when is None:
        return _invalid("Month must be formatted YYYY-MM.")
    if body is None or "amount" not in body:
        return _invalid("amount is required.")
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > 200:
        return _invalid("note must be text (max 200 characters).")
    try:
        entry = services.set_basic(target, when, body["amount"], note, request.user)
    except ConfigError as e:
        return _config_error(e)
    return Response(salary_entry(entry))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def rates(request):
    if not can_view_rates(request.user):
        return _forbidden()
    raw = request.query_params.get("year")
    if raw is None:
        year = date.today().year
    elif raw.isdigit() and len(raw) == 4 and int(raw) >= 1:
        year = int(raw)
    else:
        return _invalid("year must be a 4-digit year.")
    found = {(r.month, r.currency): r.rate_to_egp for r in ExchangeRate.objects.filter(
        month__gte=date(year, 1, 1), month__lte=date(year, 12, 1))}
    results = []
    for m in range(1, 13):
        row = {"month": f"{year:04d}-{m:02d}"}
        for cur in RATE_CURRENCIES:
            value = found.get((date(year, m, 1), cur))
            row[cur] = str(value) if value is not None else None
        results.append(row)
    return Response({"results": results})


@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def rate_detail(request, month, currency):
    if not can_edit_rates(request.user):
        return _forbidden()
    when = _month(month)
    if when is None:
        return _invalid("Month must be formatted YYYY-MM.")
    if request.method == "DELETE":
        try:
            services.delete_rate(when, currency)
        except ConfigError as e:
            return _config_error(e)
        return Response(status=204)
    body = _body(request)
    if body is None or "rate_to_egp" not in body:
        return _invalid("rate_to_egp is required.")
    try:
        rate = services.set_rate(when, currency, body["rate_to_egp"], request.user)
    except ConfigError as e:
        return _config_error(e)
    return Response({"month": month_str(rate.month), "currency": rate.currency,
                     "rate_to_egp": str(rate.rate_to_egp)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def department_rates(request):
    if not can_view_rates(request.user):
        return _forbidden()
    raw = request.query_params.get("department")
    dept = Department.objects.filter(uuid=raw).first() if raw and _is_uuid(raw) else None
    if dept is None:
        return _not_found()
    raw_month = request.query_params.get("month")
    when = date.today().replace(day=1) if raw_month is None else _month(raw_month)
    if when is None:
        return _invalid("Month must be formatted YYYY-MM.")
    sheet = services.rates_for(dept, when)
    versions = DepartmentRates.objects.filter(department=dept).order_by("-effective_from")
    return Response({
        "sheet": rates_data(sheet) if sheet else None,
        "versions": [month_str(v.effective_from) for v in versions],
    })


@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def department_rates_detail(request, uuid, month):
    if not can_edit_rates(request.user):
        return _forbidden()
    dept = Department.objects.filter(uuid=uuid).first()
    if dept is None:
        return _not_found()
    when = _month(month)
    if when is None:
        return _invalid("Month must be formatted YYYY-MM.")
    body = _body(request)
    if body is None or "american_lead_price" not in body or "steps" not in body:
        return _invalid("american_lead_price and steps are required.")
    try:
        sheet = services.save_rates(
            dept, when, body["american_lead_price"], body["steps"], request.user)
    except ConfigError as e:
        return _config_error(e)
    return Response(rates_data(sheet))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def meta(request):
    return Response({
        "can_view_rates": can_view_rates(request.user),
        "can_edit_rates": can_edit_rates(request.user),
        "can_edit_salaries": bool(is_hr_plus(request.user)),
    })
