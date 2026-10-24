import ipaddress
from typing import Optional

from django.conf import settings

from apps.attendance.models import WebPunchPolicy
from apps.users.models import FingerPrintID


def client_ip(request) -> str:
    """First X-Forwarded-For entry only when ATTENDANCE_TRUST_PROXY is on, else REMOTE_ADDR."""
    if getattr(settings, "ATTENDANCE_TRUST_PROXY", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.META.get("REMOTE_ADDR", "")


def _ip_allowed(ip: str, allowed) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowed or []:
        try:
            if addr in ipaddress.ip_network(str(entry).strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def check(user, unique_id: Optional[str], ip: str) -> Optional[str]:
    """Blocked reason (``untrusted_device`` / ``ip_not_allowed``) or None when the user may punch."""
    if user.department_id is None:
        return None
    policy = WebPunchPolicy.objects.filter(department_id=user.department_id).first()
    if policy is None:
        return None
    if policy.require_trusted_device:
        if not unique_id or not FingerPrintID.objects.filter(user=user, unique_id=unique_id).exists():
            return "untrusted_device"
    if policy.require_office_ip and not _ip_allowed(ip, policy.allowed_ips):
        return "ip_not_allowed"
    return None
