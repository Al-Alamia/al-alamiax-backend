from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework.status import HTTP_200_OK, HTTP_401_UNAUTHORIZED
from django.conf import settings
from django.core.exceptions import ValidationError
from datetime import datetime
from hashlib import md5
from rest_framework.request import Request
from apps.users.auth import Login
from auth.constants import AUTH_COOKIE
from apps.users.models import User, FingerPrintID
from apps.users.serializers import FingerPrintIDSerializer
from apps.users.services.devices import DeviceLoginError, register_login_device


@api_view(["POST"])
def login(request: Request):
    login_class = Login()
    try :
        data = login_class.login(request)
        uuid = data.get("uuid",None)
        is_superuser = data.get("is_superuser",False)
        user = User.objects.filter(uuid=uuid).first() if uuid else None
        if is_superuser : 
            data.update({"unique_id":"SuperUser"})
        elif user :
            finger = register_login_device(
                user, request.data.get("unique_id", None), request.META.get("HTTP_USER_AGENT", ""))
            data.update({"unique_id":FingerPrintIDSerializer(finger).data})
        else :
            raise NotImplementedError

        data["must_change_password"] = bool(user.must_change_password) if user else False
        status = HTTP_200_OK
        response = Response(data,status)
        response.set_cookie(AUTH_COOKIE , data[AUTH_COOKIE])
    except DeviceLoginError as e :
        response = Response({"message": e.message, "type": e.type}, HTTP_401_UNAUTHORIZED)
    except Exception as e :
        data = {
            "message" : str(e),
            "type" : str(e.__class__.__name__)
        }
        status = HTTP_401_UNAUTHORIZED
        response = Response(data,status)
    return response

def _unauthorized(message, exc_type):
    return Response({"message": message, "type": exc_type}, HTTP_401_UNAUTHORIZED)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def token_refresh(request: Request):
    value = request.data.get("refresh") if hasattr(request.data, "get") else None
    if not value or not isinstance(value, str):
        return _unauthorized("refresh token is required", "TokenError")
    try:
        old = RefreshToken(value)
        claim = settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id")
        user = User.objects.filter(uuid=old.get(claim)).first()
        if user is None or not user.is_active:
            return _unauthorized("User not found or inactive", "AuthenticationFailed")
        serializer = TokenRefreshSerializer(data={"refresh": value})
        serializer.is_valid(raise_exception=True)
        access = serializer.validated_data["access"]
        new_refresh = serializer.validated_data.get("refresh", value)
    except (TokenError, InvalidToken, ValueError, ValidationError) as e:
        return _unauthorized(str(e), e.__class__.__name__)
    exp = AccessToken(access)["exp"]
    return Response({
        AUTH_COOKIE: access,
        "refresh": new_refresh,
        "expire": datetime.utcfromtimestamp(exp).isoformat(),
    }, HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def logout(request: Request):
    value = request.data.get("refresh") if hasattr(request.data, "get") else None
    if value and isinstance(value, str):
        try:
            RefreshToken(value).blacklist()
        except TokenError:
            pass
    response = Response({"message":"Logout successfully"})
    response.delete_cookie(AUTH_COOKIE)
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def permissions(request: Request):
    """Current user's Django permissions, md5-hashed as the frontend permission store expects."""
    perms = sorted(request.user.get_all_permissions())
    return Response({
        "permissions": [md5(p.encode()).hexdigest() for p in perms],
        "allowedPages": [],
    }, HTTP_200_OK)
