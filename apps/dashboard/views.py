from datetime import datetime

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .registry import build_all


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard(request):
    return Response(build_all(request.user, datetime.now()))
