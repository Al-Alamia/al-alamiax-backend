import datetime as dt
import uuid as uuid_lib

from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.users.admin_permissions import is_top
from apps.users.views.pagination import DefaultPagination

from .. import serializers as s
from ..models import ImportBatch, ProjectGroup, TreasuryEntry
from ..services import TreasuryError, importer, ledger

__all__ = [
    "balance", "breakdown", "entries", "entry_reverse", "groups", "group_detail",
    "import_preview", "import_batches", "import_reverse",
]


class EntryPagination(DefaultPagination):
    page_size = 50


def _err(e: TreasuryError):
    body = {"message": e.message, "type": e.type}
    if e.errors:
        body["errors"] = e.errors
    return Response(body, status=e.status)


def _forbidden():
    return error("Only the owner can access the treasury.", "forbidden", 403)


def _not_found():
    return error("Not found.", "not_found", 404)


def _invalid(message):
    return error(message, "invalid", 400)


def _body(request):
    return request.data if isinstance(request.data, dict) or hasattr(request.data, "get") else {}


def _uuid(raw):
    try:
        return uuid_lib.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        raise TreasuryError("invalid", "Invalid id.")


def _month(raw):
    if not raw:
        return None
    try:
        if len(raw) != 7:
            raise ValueError
        d = dt.datetime.strptime(raw, "%Y-%m")
    except ValueError:
        raise TreasuryError("invalid", "month must be YYYY-MM.")
    return d.date().replace(day=1)


def _date(raw, field="date"):
    try:
        return dt.datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        raise TreasuryError("invalid", f"{field} must be YYYY-MM-DD.")


def _group(raw):
    """Group by uuid; None for empty."""
    if raw in (None, ""):
        return None
    group = ProjectGroup.objects.filter(pk=_uuid(raw)).first()
    if group is None:
        raise TreasuryError("invalid", "Unknown group.")
    return group


def top_only(view):
    def wrapper(request, *args, **kwargs):
        if not is_top(request.user):
            return _forbidden()
        try:
            return view(request, *args, **kwargs)
        except TreasuryError as e:
            return _err(e)
    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@top_only
def balance(request):
    month = _month(request.query_params.get("month"))
    return Response({
        "all_time": s.totals_data(ledger.balance(None)),
        "month": s.totals_data(ledger.balance(month)) if month else None})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@top_only
def breakdown(request):
    month = _month(request.query_params.get("month"))
    return Response([{"group": s.group_ref(r["group"]), "outcome": s.money(r["outcome"])}
                     for r in ledger.group_breakdown(month)])


def _filtered_entries(params):
    qs = TreasuryEntry.objects.select_related("group", "created_by")
    if params.get("direction"):
        qs = qs.filter(direction=params["direction"])
    if params.get("category"):
        qs = qs.filter(category=params["category"])
    group = params.get("group")
    if group == "none":
        qs = qs.filter(group__isnull=True)
    elif group:
        qs = qs.filter(group_id=_uuid(group))
    if params.get("date_from"):
        qs = qs.filter(date__gte=_date(params["date_from"], "date_from"))
    if params.get("date_to"):
        qs = qs.filter(date__lte=_date(params["date_to"], "date_to"))
    return qs


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@top_only
def entries(request):
    if request.method == "GET":
        pager = EntryPagination()
        page = pager.paginate_queryset(_filtered_entries(request.query_params), request)
        return pager.get_paginated_response([s.entry_data(e) for e in page])
    b = _body(request)
    entry = ledger.add_entry(
        request.user, b.get("direction"), b.get("category"), b.get("amount"),
        _date(b.get("date")), b.get("details"), _group(b.get("group")))
    return Response(s.entry_data(entry), status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@top_only
def entry_reverse(request, pk):
    entry = TreasuryEntry.objects.filter(pk=pk).first()
    if entry is None:
        return _not_found()
    reversal = ledger.reverse_entry(request.user, entry, _body(request).get("reason"))
    return Response(s.entry_data(reversal), status=201)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@top_only
def groups(request):
    if request.method == "GET":
        return Response([s.group_data(g) for g in ProjectGroup.objects.order_by("name", "uuid")])
    b = _body(request)
    group = ledger.create_group(request.user, b.get("name"), b.get("project_ids"))
    return Response(s.group_data(group), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
@top_only
def group_detail(request, pk):
    group = ProjectGroup.objects.filter(pk=pk).first()
    if group is None:
        return _not_found()
    if request.method == "DELETE":
        ledger.delete_group(group)
        return Response(status=204)
    b = _body(request)
    group = ledger.update_group(group, b.get("name"), b.get("project_ids"))
    return Response(s.group_data(group))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
@top_only
def import_preview(request):
    file = request.FILES.get("file")
    if file is None:
        return _invalid("A file is required.")
    default = _group(request.data.get("group"))
    raw = importer.parse_sheet(file)
    clean, errors = importer.validate_rows(raw, default)
    return Response({"rows": [s.row_data(r) for r in (raw if errors else clean)], "errors": errors})


def _commit_row(r):
    if not isinstance(r, dict):
        raise TreasuryError("invalid", "Each row must be an object.")
    g = r.get("group")
    if isinstance(g, dict):
        g = g.get("name")
    return {**r, "group": g or ""}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@top_only
def import_batches(request):
    if request.method == "GET":
        qs = ImportBatch.objects.select_related("created_by").order_by("-created_at")[:20]
        return Response([s.batch_data(b) for b in qs])
    b = _body(request)
    rows = b.get("rows")
    if not isinstance(rows, list):
        return _invalid("rows must be a list.")
    if len(rows) > importer.MAX_ROWS:
        raise TreasuryError("too_many_rows", f"At most {importer.MAX_ROWS} rows are allowed.")
    batch = importer.import_rows(request.user, [_commit_row(r) for r in rows], _group(b.get("group")))
    return Response({"batch_id": str(batch.uuid), "row_count": batch.row_count}, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@top_only
def import_reverse(request, pk):
    batch = ImportBatch.objects.filter(pk=pk).first()
    if batch is None:
        return _not_found()
    batch = importer.reverse_batch(request.user, batch, _body(request).get("reason"))
    return Response(s.batch_data(batch))
