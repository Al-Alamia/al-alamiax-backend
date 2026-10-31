import uuid as uuid_lib
from datetime import date

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.users.lead_permissions import scope_queryset
from apps.users.models import Lead
from apps.users.views.pagination import DefaultPagination

from . import permissions as perms
from . import services
from .models import Payment, Subscription
from .reports import list_summary
from .serializers import payment_data, subscription_data
from .services import SubscriptionError

_RELATED = ("lead", "seller", "created_by")


def _qs():
    return Subscription.objects.select_related(*_RELATED).prefetch_related("payments__recorded_by")


def _denied(exc=None):
    return error(str(getattr(exc, "detail", None) or perms.DENIED_MESSAGE), "forbidden", 403)


def _not_found():
    return error("Not found", "not_found", 404)


def _sub_error(e: SubscriptionError):
    return error(e.message, e.code, 400)


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _find_lead(user, uuid):
    lead = scope_queryset(user, Lead.objects.filter(pk=uuid)).first()
    if lead is None:
        try:
            lead = scope_queryset(user, Lead.objects.filter(pk=uuid), hidden=True).first()
        except PermissionDenied:
            lead = None
    return lead


def _get_sub(user, uuid):
    """Subscription visible to the user, else None."""
    try:
        return perms.scope_subscriptions(user, _qs()).filter(pk=uuid).first()
    except PermissionDenied:
        return None


def _get_payment(user, uuid):
    pay = Payment.objects.select_related("subscription__lead", "recorded_by").filter(pk=uuid).first()
    if pay is None or _get_sub(user, pay.subscription_id) is None:
        return None
    return pay


def _reload(user, uuid):
    return _qs().get(pk=uuid)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def lead_subscriptions(request, uuid):
    user = request.user
    lead = _find_lead(user, uuid)
    if lead is None:
        return _not_found()
    if not perms.has_access(user):
        return _denied()
    if request.method == "GET":
        caps = perms.lead_can(user, lead)
        try:
            subs = perms.scope_subscriptions(user, _qs().filter(lead=lead))
        except PermissionDenied as e:
            return _denied(e)
        sellers = ([{"uuid": str(u.pk), "name": u.get_full_name() or u.username}
                    for u in perms.seller_choices(lead)] if caps["choose_seller"] else [])
        return Response({
            "can": {"create": caps["create"], "choose_seller": caps["choose_seller"]},
            "sellers": sellers,
            "results": [subscription_data(user, s) for s in subs],
        })
    try:
        sub = services.create_subscription(user, lead, _body(request))
    except PermissionDenied as e:
        return _denied(e)
    except SubscriptionError as e:
        return _sub_error(e)
    return Response(subscription_data(user, _reload(user, sub.pk)), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def subscription_detail(request, uuid):
    user = request.user
    sub = _get_sub(user, uuid)
    if sub is None:
        return _not_found()
    try:
        if request.method == "DELETE":
            services.delete_subscription(user, sub)
            return Response(status=204)
        services.update_subscription(user, sub, _body(request))
    except PermissionDenied as e:
        return _denied(e)
    except SubscriptionError as e:
        return _sub_error(e)
    return Response(subscription_data(user, _reload(user, uuid)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def subscription_cancel(request, uuid):
    user = request.user
    sub = _get_sub(user, uuid)
    if sub is None:
        return _not_found()
    try:
        services.cancel_subscription(user, sub, _body(request).get("reason"))
    except PermissionDenied as e:
        return _denied(e)
    except SubscriptionError as e:
        return _sub_error(e)
    return Response(subscription_data(user, _reload(user, uuid)))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def subscription_payments(request, uuid):
    user = request.user
    sub = _get_sub(user, uuid)
    if sub is None:
        return _not_found()
    try:
        pay = services.add_payment(user, sub, _body(request))
    except PermissionDenied as e:
        return _denied(e)
    except SubscriptionError as e:
        return _sub_error(e)
    return Response(payment_data(user, Payment.objects.select_related("recorded_by", "subscription__lead").get(pk=pay.pk)),
                    status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def payment_detail(request, uuid):
    user = request.user
    pay = _get_payment(user, uuid)
    if pay is None:
        return _not_found()
    try:
        if request.method == "DELETE":
            services.delete_payment(user, pay)
            return Response(status=204)
        pay = services.update_payment(user, pay, _body(request))
    except PermissionDenied as e:
        return _denied(e)
    except SubscriptionError as e:
        return _sub_error(e)
    return Response(payment_data(user, Payment.objects.select_related("recorded_by", "subscription__lead").get(pk=pay.pk)))


def _parse_day(raw):
    try:
        if len(raw) != 10:
            return None
        return date.fromisoformat(raw)
    except ValueError:
        return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subscription_list(request):
    user = request.user
    try:
        base = perms.scope_subscriptions(user, Subscription.objects.all())
    except PermissionDenied as e:
        return _denied(e)
    if not perms.has_access(user):
        return _denied()
    q = request.query_params
    start = end = None
    if q.get("from"):
        start = _parse_day(q["from"])
        if start is None:
            return error("from is invalid", "invalid", 400)
    if q.get("to"):
        end = _parse_day(q["to"])
        if end is None:
            return error("to is invalid", "invalid", 400)
    if start and end and start > end:
        return error("from must not be after to", "invalid", 400)
    if start:
        base = base.filter(start_date__gte=start)
    if end:
        base = base.filter(start_date__lte=end)
    if q.get("seller"):
        try:
            base = base.filter(seller_id=uuid_lib.UUID(q["seller"]))
        except ValueError:
            return error("seller is invalid", "invalid", 400)
    for field in ("kind", "market", "currency"):
        if q.get(field):
            base = base.filter(**{field: q[field]})
    status = q.get("status")
    if status:
        today = date.today()
        if status == "cancelled":
            base = base.filter(cancelled_at__isnull=False)
        elif status == "expired":
            base = base.filter(cancelled_at__isnull=True, end_date__lt=today)
        elif status == "active":
            base = base.filter(cancelled_at__isnull=True, end_date__gte=today)
        else:
            return error("status is invalid", "invalid", 400)
    search = (q.get("search") or "").strip()
    if search:
        base = base.filter(Q(lead__name__icontains=search) | Q(lead__phone__icontains=search)
                           | Q(plan_name__icontains=search))
    summary = list_summary(base, start, end)
    pager = DefaultPagination()
    page = pager.paginate_queryset(
        base.select_related(*_RELATED).prefetch_related("payments").order_by("-start_date", "-created_at", "uuid"),
        request)
    response = pager.get_paginated_response([subscription_data(user, s, with_payments=False) for s in page])
    response.data["summary"] = summary
    return response
