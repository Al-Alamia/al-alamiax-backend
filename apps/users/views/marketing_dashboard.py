from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.services.marketing_dashboard import build_dashboard


def _invalid(message):
    return Response({"message": message, "type": "invalid"}, status=400)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def marketing_dashboard(request):
    mode = request.query_params.get("mode") or "month"
    if mode not in ("day", "month"):
        return _invalid("mode must be 'day' or 'month'.")
    raw = request.query_params.get("date")
    try:
        d = date.fromisoformat(raw) if raw else date.today()
    except ValueError:
        return _invalid("date must be YYYY-MM-DD.")
    return Response(build_dashboard(request.user, mode, d))
