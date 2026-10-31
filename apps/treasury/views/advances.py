import datetime as dt

from django.db import IntegrityError
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.monthly_basic.permissions import can_manage_basic, list_scope
from apps.payroll_config.services import basic_for
from apps.users.models import User

from .. import serializers as s
from ..models import Advance
from ..services import TreasuryError
from ..services import advances
from ..types import AdvanceStatus
from .ledger import EntryPagination, _body, _err, _not_found, _uuid

__all__ = ["advances_list", "advances_mine", "advances_limit", "advance_approve", "advance_reject",
           "advance_withdraw", "advance_cancel"]


def guarded(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except TreasuryError as e:
            return _err(e)
    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _user(raw):
    user = User.objects.filter(pk=_uuid(raw)).first()
    if user is None:
        raise TreasuryError("invalid", "Unknown user.")
    return user


def _qs():
    return Advance.objects.select_related("user", "requested_by", "decided_by").prefetch_related(
        "schedule").order_by("-created_at")


def _month_of(key):
    from apps.monthly_basic import services as ms
    try:
        return ms.month_of(key)
    except ms.BasicError:
        raise TreasuryError("invalid", "Invalid period.")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@guarded
def advances_list(request):
    viewer = request.user
    if request.method == "POST":
        b = _body(request)
        target = _user(b["user"]) if b.get("user") not in (None, "") else viewer
        installments = b.get("installments")
        try:
            adv = advances.request_advance(viewer, target, b.get("amount"), installments,
                                           b.get("start_period"), b.get("reason") or "")
        except IntegrityError:
            raise TreasuryError("pending_exists", "This user already has a pending advance.")
        return Response(s.advance_data(adv, viewer), status=201)
    scope = list_scope(viewer)
    if scope is None:
        return error("You cannot list advances.", "forbidden", 403)
    params = request.query_params
    qs = _qs().filter(user__in=scope)
    if params.get("status"):
        qs = qs.filter(status=params["status"])
    if params.get("user"):
        qs = qs.filter(user_id=_uuid(params["user"]))
    if params.get("period"):
        _month_of(params["period"])
        qs = qs.filter(Q(schedule__period=params["period"])
                       | Q(status=AdvanceStatus.PENDING, start_period=params["period"])).distinct()
    pager = EntryPagination()
    page = pager.paginate_queryset(qs, request)
    return pager.get_paginated_response([s.advance_data(a, viewer) for a in page])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@guarded
def advances_mine(request):
    return Response([s.advance_data(a, request.user) for a in _qs().filter(user=request.user)])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@guarded
def advances_limit(request):
    viewer = request.user
    raw = request.query_params.get("user")
    target = _user(raw) if raw else viewer
    if target.pk != viewer.pk and not can_manage_basic(viewer, target):
        return error("You cannot view this user's limit.", "forbidden", 403)
    month = _month_of(request.query_params.get("start_period"))
    basic = basic_for(target, month)
    value = s.money(basic) if basic is not None else None
    return Response({"basic": value, "max": value})


def _decision(request, pk, fn):
    adv = Advance.objects.filter(pk=pk).first()
    if adv is None:
        return _not_found()
    fn(request.user, adv, _body(request))
    return Response(s.advance_data(_qs().get(pk=pk), request.user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@guarded
def advance_approve(request, pk):
    return _decision(request, pk, lambda u, a, b: advances.approve_advance(u, a, b.get("note") or ""))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@guarded
def advance_reject(request, pk):
    return _decision(request, pk, lambda u, a, b: advances.reject_advance(u, a, b.get("note")))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@guarded
def advance_withdraw(request, pk):
    return _decision(request, pk, lambda u, a, b: advances.withdraw_advance(u, a))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@guarded
def advance_cancel(request, pk):
    return _decision(request, pk, lambda u, a, b: advances.cancel_advance(u, a, b.get("reason")))
