from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.notifications.services import notify
from apps.notifications.types import NotificationKinds
from apps.users.admin_permissions import can_manage_devices, device_approvers
from apps.users.models import FingerPrintID
from apps.users.services.users import revoke_refresh_tokens
from apps.users.types import DeviceStatus

MAX_PENDING_DEVICES = 3
DEFAULT_DEVICE_NAME = "New device"


class DeviceLoginError(Exception):
    def __init__(self, type, message):
        super().__init__(message)
        self.type = type
        self.message = message


class DeviceError(Exception):
    def __init__(self, type, message, status=400):
        super().__init__(message)
        self.type = type
        self.message = message
        self.status = status


def device_name(user_agent: str) -> str:
    ua = user_agent or ""
    browser = next((name for token, name in (
        ("Edg", "Edge"), ("Firefox", "Firefox"), ("Chrome", "Chrome"), ("Safari", "Safari")) if token in ua), None)
    os_name = next((name for token, name in (
        ("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iOS"),
        ("Mac OS", "Mac"), ("Macintosh", "Mac"), ("Linux", "Linux")) if token in ua), None)
    if browser and os_name:
        return f"{browser} on {os_name}"
    return browser or os_name or DEFAULT_DEVICE_NAME


def register_login_device(user, unique_id, user_agent) -> FingerPrintID:
    """Return the approved device for this login (touching last_used_at) or raise DeviceLoginError."""
    if not isinstance(unique_id, str) or not unique_id.strip():
        raise DeviceLoginError("device_required", "A device id is required to log in")
    unique_id = unique_id.strip()
    device = FingerPrintID.objects.filter(user=user, unique_id=unique_id).first()
    if device is None:
        device = _create_pending(user, unique_id, user_agent or "")
    if device.status == DeviceStatus.APPROVED:
        device.last_used_at = timezone.now()
        device.save(update_fields=["last_used_at"])
        return device
    if device.status == DeviceStatus.REJECTED:
        raise DeviceLoginError("device_rejected", "This device was rejected")
    raise DeviceLoginError("device_pending", "This device is waiting for approval")


def _create_pending(user, unique_id, user_agent):
    pending = FingerPrintID.objects.filter(user=user, status=DeviceStatus.PENDING).count()
    if pending >= MAX_PENDING_DEVICES:
        raise DeviceLoginError("device_pending", "Too many devices are waiting for approval")
    name = device_name(user_agent)
    try:
        with transaction.atomic():
            device = FingerPrintID.objects.create(
                user=user, unique_id=unique_id, name=name, user_agent=user_agent[:255],
                status=DeviceStatus.PENDING)
    except IntegrityError:  # concurrent login with the same device id
        return FingerPrintID.objects.get(user=user, unique_id=unique_id)
    approvers = device_approvers(user)
    if approvers:
        notify(approvers, f"{user} is waiting for approval of a new device ({name})",
               kind=NotificationKinds.DEVICE, title="Device", link=f"/users/{user.uuid}#devices", sender=None)
    return device


def _check_manage(actor, device):
    if not can_manage_devices(actor, device.user):
        raise DeviceError("forbidden", "You are not allowed to manage this device", 403)


def _decide(actor, device, status, verb):
    _check_manage(actor, device)
    if device.status != DeviceStatus.PENDING:
        raise DeviceError("invalid", "Only pending devices can be approved or rejected", 400)
    device.status = status
    device.decided_by = actor
    device.decided_at = timezone.now()
    setattr(device, "__by", actor)
    device.save()
    notify([device.user], f"Your device {device.name} was {verb}", kind=NotificationKinds.DEVICE,
           title="Device", link="/profile", sender=actor)
    return device


def approve_device(actor, device):
    return _decide(actor, device, DeviceStatus.APPROVED, "approved")


def reject_device(actor, device):
    return _decide(actor, device, DeviceStatus.REJECTED, "rejected")


def revoke_device(actor, device):
    _check_manage(actor, device)
    setattr(device, "__by", actor)
    with transaction.atomic():
        device.delete()
        revoke_refresh_tokens(device.user)


def rename_device(actor, device, name):
    _check_manage(actor, device)
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > 100:
        raise DeviceError("invalid", "Name must be 1-100 characters", 400)
    device.name = name
    setattr(device, "__by", actor)
    device.save(update_fields=["name"])
    return device
