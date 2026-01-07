from rest_framework_simplejwt.authentication import JWTAuthentication , Token
from rest_framework.exceptions import AuthenticationFailed
from django.http.request import HttpRequest
from django.conf import settings
from django.contrib.auth import get_user_model
from typing import Optional , Tuple
import json

User = get_user_model()


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
        return self.check_token(request.COOKIES ,  settings.SIMPLE_JWT["AUTH_COOKIE"])

class HeaderAuthentication(JWTAuthenticationMixin):
    def authenticate(self, request:HttpRequest):
        return self.check_token(dict(request.headers) ,settings.SIMPLE_JWT["AUTH_HEADER"] )

class BodyAuthentication(JWTAuthenticationMixin):
    def authenticate(self, request:HttpRequest):
        try :
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = {}
        return self.check_token(data,settings.SIMPLE_JWT["AUTH_BODY"] )
