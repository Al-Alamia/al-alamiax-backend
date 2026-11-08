import uuid as uuid_lib
from datetime import date, datetime

from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.teams.permissions import supervised_users
from apps.users.models import Department, User

from .errors import ReportError
from .models import ReportSubmission, ReportType
from .permissions import can_manage_reports, can_view_board
from .serializers import definition_data, submission_data, type_data
from .services.audience import is_required, required_users
from .services.board import build_board
from .services.definition import save_definition
from .services.periods import recent_periods
from .services.submissions import can_edit, save_submission, submission_values
from .types import Frequency, SubmissionStatus

AUTH = [IsAuthenticated]


def _today() -> date:
    return date.today()


def _invalid(message: str, fields=None) -> Response:
    return Response({"message": message, "type": "invalid", "fields": fields or {}}, status=400)


def _report_error(e: ReportError) -> Response:
    return Response({"message": e.message, "type": e.type, "fields": e.fields}, status=400)


def _not_found() -> Response:
    return error("Not found", "not_found", 404)


def _forbidden() -> Response:
    return error("Forbidden", "forbidden", 403)


def _parse_date(raw):
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _active_types():
    return ReportType.objects.filter(is_active=True)


def _assigned_types(user):
    return [rt for rt in _active_types().prefetch_related("departments", "excluded_users")
            if required_users(rt).filter(pk=user.pk).exists()]


@api_view(["GET"])
@permission_classes(AUTH)
def access(request):
    user = request.user
    board = can_view_board(user)
    return Response({"fill": bool(_assigned_types(user)), "view_board": board,
                     "manage": can_manage_reports(user), "dashboard": board})


@api_view(["GET"])
@permission_classes(AUTH)
def my(request):
    user, today = request.user, _today()
    out = []
    for rt in _assigned_types(user):
        subs = {s.period_start: s for s in ReportSubmission.objects.filter(report_type=rt, user=user)}
        periods = []
        for start, end in recent_periods(rt, today, 7):
            sub = subs.get(start)
            if sub is not None:
                status = SubmissionStatus.LATE if sub.is_late else SubmissionStatus.SUBMITTED
            elif is_required(rt, user, start, end, today):
                status = SubmissionStatus.MISSING
            else:
                continue
            ok, reason = can_edit(rt, user, start, end, today)
            periods.append({"start": start.isoformat(), "end": end.isoformat(), "status": status.value,
                            "can_edit": ok, "reason": reason,
                            "submission": str(sub.uuid) if sub else None})
        out.append({"uuid": str(rt.uuid), "name": rt.name, "description": rt.description,
                    "frequency": rt.frequency, "edit_window_days": rt.edit_window_days,
                    "sections": definition_data(rt, active_only=True), "periods": periods})
    return Response(out)


@api_view(["GET"])
@permission_classes(AUTH)
def submission_detail(request, uuid):
    sub = (ReportSubmission.objects.select_related("report_type", "user").filter(uuid=uuid).first())
    viewer = request.user
    if sub is None or not (sub.user_id == viewer.pk
                           or supervised_users(viewer).filter(pk=sub.user_id).exists()):
        return _not_found()
    if sub.user_id == viewer.pk:
        ok, reason = can_edit(sub.report_type, viewer, sub.period_start, sub.period_end, _today())
    else:
        ok, reason = False, "not_owner"
    return Response(submission_data(sub, ok, reason))


@api_view(["POST"])
@permission_classes(AUTH)
def submit(request, uuid):
    rt = ReportType.objects.filter(uuid=uuid).first()
    if rt is None:
        return _not_found()
    body = request.data
    if not isinstance(body, dict):
        return _invalid("Invalid body.")
    when = _parse_date(body.get("date"))
    if when is None:
        return _invalid("A valid date is required.")
    values = body.get("values")
    if not isinstance(values, dict):
        return _invalid("Values must be an object.")
    try:
        sub = save_submission(rt, request.user, when, values, _today())
    except ReportError as e:
        return _report_error(e)
    sub = ReportSubmission.objects.select_related("report_type", "user").get(pk=sub.pk)
    ok, reason = can_edit(rt, request.user, sub.period_start, sub.period_end, _today())
    return Response(submission_data(sub, ok, reason))


@api_view(["GET"])
@permission_classes(AUTH)
def board(request, uuid):
    if not can_view_board(request.user):
        return _forbidden()
    rt = ReportType.objects.filter(uuid=uuid).first()
    if rt is None:
        return _not_found()
    raw = request.query_params.get("date")
    when = _today() if not raw else _parse_date(raw)
    if when is None:
        return _invalid("Invalid date.")
    project = request.query_params.get("project") or None
    if project is not None:
        try:
            uuid_lib.UUID(project)
        except ValueError:
            return _invalid("Invalid project.")
    data = build_board(rt, request.user, when, _today(), project)
    data["period"] = {k: v.isoformat() for k, v in data["period"].items()}
    return Response(data)


@api_view(["GET"])
@permission_classes(AUTH)
def type_options(request):
    if not can_view_board(request.user):
        return _forbidden()
    return Response([{"uuid": str(t.uuid), "name": t.name, "frequency": t.frequency}
                     for t in _active_types()])


def _uuid_list(body, key, default):
    raw = body.get(key, default)
    if not isinstance(raw, list):
        raise ReportError(f"{key} must be a list.", "invalid")
    ids = []
    for x in raw:
        try:
            ids.append(uuid_lib.UUID(str(x)))
        except ValueError:
            raise ReportError(f"Invalid uuid in {key}.", "invalid")
    return ids


def _check_sections(sections):
    if not isinstance(sections, list):
        raise ReportError("Sections must be a list.", "invalid")
    seen = set()
    for s in sections:
        if not isinstance(s, dict) or not isinstance(s.get("fields"), list):
            raise ReportError("Each section needs a fields list.", "invalid")
        items = [s] + s["fields"]
        for item in items:
            if not isinstance(item, dict):
                raise ReportError("Invalid field.", "invalid")
            u = item.get("uuid")
            if u:
                if str(u) in seen:
                    raise ReportError("Duplicate uuid in definition.", "invalid")
                seen.add(str(u))


def _settings(body, rt):
    """Validated model-field values from the payload (missing keys keep the current value)."""
    def cur(key, default):
        return getattr(rt, key) if rt is not None else default

    name = body.get("name", cur("name", None))
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ReportError("A valid name is required.", "invalid")
    name = name.strip()
    clash = ReportType.objects.filter(name__iexact=name)
    if rt is not None:
        clash = clash.exclude(pk=rt.pk)
    if clash.exists():
        raise ReportError("A report with this name already exists.", "invalid", {"name": "Name already used."})
    desc = body.get("description", cur("description", ""))
    if not isinstance(desc, str):
        raise ReportError("Invalid description.", "invalid")
    freq = body.get("frequency", cur("frequency", Frequency.DAILY))
    if freq not in Frequency.values:
        raise ReportError("Invalid frequency.", "invalid")
    window = body.get("edit_window_days", cur("edit_window_days", None))
    if window is not None and (isinstance(window, bool) or not isinstance(window, int)
                               or not 0 <= window <= 32767):
        raise ReportError("Invalid edit window.", "invalid")
    order = body.get("order", cur("order", 0))
    if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 32767:
        raise ReportError("Invalid order.", "invalid")
    out = {"name": name, "description": desc, "frequency": freq, "edit_window_days": window, "order": order}
    for key in ("is_active", "remind_agents", "digest_leaders"):
        v = body.get(key, cur(key, True if key == "is_active" else False))
        if not isinstance(v, bool):
            raise ReportError(f"Invalid {key}.", "invalid")
        out[key] = v
    raw_time = body.get("remind_at")
    if raw_time is None:
        out["remind_at"] = cur("remind_at", datetime(2000, 1, 1, 20, 0).time())
    else:
        try:
            out["remind_at"] = datetime.strptime(raw_time, "%H:%M").time()
        except (TypeError, ValueError):
            raise ReportError("Invalid remind_at.", "invalid")
    return out


def _write_type(request, rt=None):
    body = request.data
    if not isinstance(body, dict):
        raise ReportError("Invalid body.", "invalid")
    settings = _settings(body, rt)
    dept_ids = _uuid_list(body, "departments", []) if "departments" in body else None
    user_ids = _uuid_list(body, "excluded_users", []) if "excluded_users" in body else None
    sections = body.get("sections") if "sections" in body else None
    if sections is None and rt is None:
        sections = []
    if sections is not None:
        _check_sections(sections)
    depts = users = None
    if dept_ids is not None:
        depts = list(Department.objects.filter(uuid__in=dept_ids))
        if len(depts) != len(set(dept_ids)):
            raise ReportError("Unknown department.", "invalid")
    if user_ids is not None:
        users = list(User.objects.filter(uuid__in=user_ids))
        if len(users) != len(set(user_ids)):
            raise ReportError("Unknown user.", "invalid")
    with transaction.atomic():
        if rt is None:
            rt = ReportType.objects.create(**settings)
        else:
            for k, v in settings.items():
                setattr(rt, k, v)
            rt.save()
        if depts is not None:
            rt.departments.set(depts)
        if users is not None:
            rt.excluded_users.set(users)
        if sections is not None:
            save_definition(rt, sections)
    return rt


def _fresh(rt):
    return ReportType.objects.prefetch_related("departments", "excluded_users").get(pk=rt.pk)


@api_view(["GET", "POST"])
@permission_classes(AUTH)
def types(request):
    if not can_manage_reports(request.user):
        return _forbidden()
    if request.method == "GET":
        qs = ReportType.objects.prefetch_related("departments", "excluded_users")
        return Response([type_data(t) for t in qs])
    try:
        rt = _write_type(request)
    except ReportError as e:
        return _report_error(e)
    return Response(type_data(_fresh(rt)), status=201)


@api_view(["PUT", "DELETE"])
@permission_classes(AUTH)
def type_detail(request, uuid):
    if not can_manage_reports(request.user):
        return _forbidden()
    rt = ReportType.objects.filter(uuid=uuid).first()
    if rt is None:
        return _not_found()
    if request.method == "DELETE":
        if rt.submissions.exists():
            return error("This report has submissions; deactivate it instead.", "has_submissions", 400)
        rt.delete()
        return Response(status=204)
    try:
        rt = _write_type(request, rt)
    except ReportError as e:
        return _report_error(e)
    return Response(type_data(_fresh(rt)))
