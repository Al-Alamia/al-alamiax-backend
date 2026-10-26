from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.views import error
from apps.users.models import Profile
from apps.users.serializers.admin import brief, user_name

MAX_PICTURE_BYTES = 5 * 1024 * 1024
MAX_ABOUT = 2000


def _is_image(head: bytes) -> bool:
    return (head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG\r\n\x1a\n")
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP"))


def profile_json(request, profile) -> dict:
    user = profile.user
    return {
        "phone": profile.phone,
        "picture": request.build_absolute_uri(profile.picture.url) if profile.picture else None,
        "telegram_id": profile.telegram_id, "about": profile.about,
        "user": {"uuid": str(user.uuid), "username": user.username, "name": user_name(user),
                 "role": user.role, "title": user.title,
                 "department": brief(user.department), "project": brief(user.project)},
    }


def _clean_phone(raw):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if not isinstance(raw, str):
        raise ValueError("'phone' must be a string.")
    try:
        return Profile._meta.get_field("phone").clean(raw.strip(), None)
    except ValidationError as exc:
        raise ValueError(" ".join(exc.messages))


def _clean_telegram(raw):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    text = str(raw).strip()
    if isinstance(raw, bool) or not (text.isascii() and text.isdecimal()) or int(text) <= 0 \
            or int(text) > 2_147_483_647:
        raise ValueError("'telegram_id' must be a positive integer.")
    return int(text)


def _clean_about(raw):
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("'about' must be a string.")
    if len(raw) > MAX_ABOUT:
        raise ValueError(f"'about' is too long (max {MAX_ABOUT}).")
    return raw.strip()


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def me_profile(request):
    user = request.user
    profile, _ = Profile.objects.select_related("user__department", "user__project").get_or_create(user=user)
    if request.method == "PATCH":
        data = request.data
        if not hasattr(data, "get"):
            return error("Request body must be an object.", "invalid", 400)
        picture = request.FILES.get("picture")
        if picture is not None:
            if picture.size > MAX_PICTURE_BYTES:
                return error("The picture must be 5 MB or smaller.", "file_too_large", 400)
            head = picture.read(12)
            picture.seek(0)
            if not _is_image(head):
                return error("The picture must be a JPEG, PNG or WEBP image.", "file_type", 400)
        try:
            values = {}
            if "phone" in data:
                values["phone"] = _clean_phone(data.get("phone"))
            if "telegram_id" in data:
                values["telegram_id"] = _clean_telegram(data.get("telegram_id"))
            if "about" in data:
                values["about"] = _clean_about(data.get("about"))
        except ValueError as exc:
            return error(str(exc), "invalid", 400)
        for name, value in values.items():
            setattr(profile, name, value)
        if picture is not None:
            profile.picture = picture
        setattr(profile, "__by", user)
        profile.save()
    return Response(profile_json(request, profile))
