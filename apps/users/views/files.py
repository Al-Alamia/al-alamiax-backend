from django.http import FileResponse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.users.admin_permissions import can_manage_files, can_view_files, can_view_user
from apps.users.models import User, UserFile
from apps.users.serializers.admin import user_name
from apps.users.services.files import FileError, delete_user_file, safe_download_name, save_user_file


def file_json(viewer, f) -> dict:
    up = f.uploaded_by
    return {
        "uuid": str(f.uuid), "title": f.title, "category": f.category, "size": f.size,
        "content_type": f.content_type, "created_at": f.created_at,
        "uploaded_by": {"uuid": str(up.uuid), "name": user_name(up)} if up else None,
        "can": {"delete": can_manage_files(viewer, f.user)},
    }


def _not_found():
    return error("Not found", "not_found", 404)


def _files(user):
    return UserFile.objects.filter(user=user).select_related("user", "uploaded_by").order_by("-created_at")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def user_files(request, uuid):
    viewer = request.user
    user = User.objects.filter(uuid=uuid).first()
    if user is None or not can_view_user(viewer, user):
        return _not_found()
    if request.method == "POST":
        data = request.data
        try:
            f = save_user_file(viewer, user, data.get("title"), data.get("category"), request.FILES.get("file"))
        except FileError as exc:
            return error(exc.message, exc.type, exc.status)
        return Response(file_json(viewer, f), status=201)
    if not can_view_files(viewer, user):
        return error("You are not allowed to view these files", "forbidden", 403)
    return Response([file_json(viewer, f) for f in _files(user)])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_files(request):
    return Response([file_json(request.user, f) for f in _files(request.user)])


def _file(request, uuid):
    f = UserFile.objects.select_related("user", "uploaded_by").filter(uuid=uuid).first()
    return f if f is not None and can_view_user(request.user, f.user) else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download(request, uuid):
    f = _file(request, uuid)
    if f is None:
        return _not_found()
    if not can_view_files(request.user, f.user):
        return error("You are not allowed to view these files", "forbidden", 403)
    response = FileResponse(f.file.open("rb"), as_attachment=True,
                            filename=safe_download_name(f.title, f.content_type),
                            content_type=f.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def file_detail(request, uuid):
    f = _file(request, uuid)
    if f is None:
        return _not_found()
    try:
        delete_user_file(request.user, f)
    except FileError as exc:
        return error(exc.message, exc.type, exc.status)
    return Response(status=204)
