from rest_framework_simplejwt.authentication import JWTAuthentication , Token
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from django.http.request import HttpRequest
from django.conf import settings
from django.contrib.auth import get_user_model
from typing import Optional , Tuple
import json

User = get_user_model()


MUST_CHANGE_ALLOWED_PATHS = (
    "/api/users/login",  # Login's own token-reuse path runs these classes directly
    "/api/users/change_password",
    "/api/users/logout",
    "/api/users/token/refresh",
)
MUST_CHANGE_GET_PATHS = ("/api/users/me/profile",)


def enforce_password_change(request, credentials):
    """Block users flagged ``must_change_password`` from everything but the password-change flow."""
    if not isinstance(credentials, tuple):
        return credentials
    user = credentials[0]
    if getattr(user, "must_change_password", False):
        path = request.path
        if not (path in MUST_CHANGE_ALLOWED_PATHS
                or (request.method == "GET" and path in MUST_CHANGE_GET_PATHS)):
            raise PermissionDenied(detail={"message": "Password change required",
                                           "type": "password_change_required"})
    return credentials


class EnforcedJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        return enforce_password_change(request, super().authenticate(request))


class JWTAuthenticationMixin(JWTAuthentication):
    def check_token(self , data:dict , auth_key:str )-> Optional[Tuple[User,Token]]:
        if isinstance(data , dict):
            token = data.copy().get(auth_key , None)
            if token is None:
                return None
            try:
                validated_token = self.get_validated_token(token)
                user = self.get_user(validated_token)
            except AuthenticationFailed:
                return None
            return (user , validated_token)


class CookieAuthentication(JWTAuthenticationMixin):
    def authenticate(self, request:HttpRequest):
        return enforce_password_change(request, self.check_token(request.COOKIES ,  settings.SIMPLE_JWT["AUTH_COOKIE"]))

class HeaderAuthentication(JWTAuthenticationMixin):
    def authenticate(self, request:HttpRequest):
        return enforce_password_change(request, self.check_token(dict(request.headers) ,settings.SIMPLE_JWT["AUTH_HEADER"] ))

class BodyAuthentication(JWTAuthenticationMixin):
    def authenticate(self, request:HttpRequest):
        try :
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = {}
        return enforce_password_change(request, self.check_token(data,settings.SIMPLE_JWT["AUTH_BODY"] ))
