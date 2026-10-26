from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.users.admin_permissions import can_manage_devices, can_view_devices, can_view_user, visible_users
from apps.users.models import FingerPrintID, User
from apps.users.serializers.admin import user_name
from apps.users.services.devices import (
    DeviceError, approve_device, reject_device, rename_device, revoke_device)
from apps.users.types import DeviceStatus


def device_json(viewer, device, with_user=False) -> dict:
    manage = can_manage_devices(viewer, device.user)
    pending = device.status == DeviceStatus.PENDING
    data = {
        "uuid": str(device.uuid), "name": device.name, "unique_id": device.unique_id,
        "status": device.status, "user_agent": device.user_agent, "last_used_at": device.last_used_at,
        "created_at": device.created_at,
        "decided_by": ({"uuid": str(device.decided_by.uuid), "name": user_name(device.decided_by)}
                       if device.decided_by else None),
        "decided_at": device.decided_at,
        "can": {"approve": manage and pending, "reject": manage and pending,
                "rename": manage, "revoke": manage},
    }
    if with_user:
        data["user"] = {"uuid": str(device.user.uuid), "name": user_name(device.user),
                        "username": device.user.username}
    return data


def _not_found():
    return error("Not found", "not_found", 404)


def _device(request, uuid):
    device = FingerPrintID.objects.select_related("user", "decided_by").filter(uuid=uuid).first()
    return device if device is not None and can_view_user(request.user, device.user) else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_devices(request, uuid):
    user = User.objects.filter(uuid=uuid).first()
    if user is None or not can_view_user(request.user, user):
        return _not_found()
    if not can_view_devices(request.user, user):
        return error("You are not allowed to view these devices", "forbidden", 403)
    devices = (FingerPrintID.objects.filter(user=user).select_related("user", "decided_by")
               .order_by("-created_at"))
    return Response([device_json(request.user, d) for d in devices])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending(request):
    viewer = request.user
    devices = (FingerPrintID.objects.filter(status=DeviceStatus.PENDING, user__in=visible_users(viewer))
               .select_related("user", "decided_by").order_by("-created_at"))
    return Response([device_json(viewer, d, with_user=True) for d in devices
                     if can_manage_devices(viewer, d.user)])


def _decide(request, uuid, action):
    device = _device(request, uuid)
    if device is None:
        return _not_found()
    try:
        action(request.user, device)
    except DeviceError as exc:
        return error(exc.message, exc.type, exc.status)
    return Response(device_json(request.user, device))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def approve(request, uuid):
    return _decide(request, uuid, approve_device)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reject(request, uuid):
    return _decide(request, uuid, reject_device)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def device_detail(request, uuid):
    device = _device(request, uuid)
    if device is None:
        return _not_found()
    try:
        if request.method == "DELETE":
            revoke_device(request.user, device)
            return Response(status=204)
        data = request.data
        name = data.get("name") if hasattr(data, "get") else None
        rename_device(request.user, device, name)
    except DeviceError as exc:
        return error(exc.message, exc.type, exc.status)
    return Response(device_json(request.user, device))
