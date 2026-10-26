from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from apps.attendance.views import error
from apps.users.admin_permissions import can_view_history, can_view_user
from apps.users.models import User
from apps.users.services.history import diff_entries, user_actions, user_history
from apps.users.views.pagination import DefaultPagination


def _paged(request, uuid, rows_for):
    user = User.objects.filter(uuid=uuid).first()
    if user is None or not can_view_user(request.user, user):
        return error("Not found", "not_found", 404)
    if not can_view_history(request.user, user):
        return error("You are not allowed to view this history", "forbidden", 403)
    pager = DefaultPagination()
    page = pager.paginate_queryset(rows_for(user), request)
    return pager.get_paginated_response(diff_entries(page))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def history(request, uuid):
    return _paged(request, uuid, user_history)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def actions(request, uuid):
    return _paged(request, uuid, user_actions)
