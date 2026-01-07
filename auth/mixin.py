from django.http.request import HttpRequest
from rest_framework.request import Request
from typing import Optional , List , Tuple , Union
from apps.users.AuthenticationClasses import User , JWTAuthenticationMixin , Token
from django.contrib.auth import  authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import AuthenticationFailed
from .constants import (
    AUTH_COOKIE ,
    EXPIRE , 
    REFRESH_COOKIE ,
)
from datetime import datetime
from abc import ABCMeta
import json


class AuthenticateMixins(metaclass=ABCMeta):
    """
    you can add auth_classes attr with all auth classes  
    auth_classes type is  List[JWTAuthenticationMixin]
    
    Usage :
    ```
        class AuthenticateUser(AuthenticateMixins):
            auth_classes = [
                CookieAuthentication ,
                HeaderAuthentication ,
                BodyAuthentication  , 
            ]

        user , token = AuthenticateUser(request)
    ```
        Note : return (None , None ) if not authinticated else return User from django setting and Token 
    """
    auth_classes:List[JWTAuthenticationMixin] = []

    @staticmethod
    def get_user_from_request_recursion(request, auth_classes: List[JWTAuthenticationMixin]) -> Optional[Tuple[User , Token]]:
        auth_classes = auth_classes.copy()
        if len(auth_classes) != 0:
            cls = auth_classes.pop(0)
            credentials = cls().authenticate(request)
            if isinstance(credentials, tuple):
                return credentials
            else:
                return AuthenticateMixins.get_user_from_request_recursion(request, auth_classes)

    def __new__(cls ,request:HttpRequest , *args , **kwargs) -> Union[Tuple[User , Token] , Tuple[None , None]]:
        credentials = cls.get_user_from_request_recursion( request=request ,auth_classes = cls.auth_classes)
        return credentials if not isinstance(credentials,type(None)) else (None , None)
    

class LoginMixins(metaclass=ABCMeta):
    """
    required attrs :
        user_serializer
        auth_class

    default attrs :
        auth_fields:List[str] = ['username','password']

    Usage :
    ```
        class Login(LoginMixins):
            auth_class = AuthenticateUser
            user_serializer =  UserSerializer

        obj = Login()
        try :
            data = obj.login(request)
                
        except Exception as e :
            data = {
                'message':str(e),
                'error_type' : str(type(e))
                }
        return Response(data)
    ```
        Note : return (None , None ) if not authinticated else return User from django setting and Token 
    """

    user_serializer = None
    auth_fields:List[str] = ['username','password']
    auth_class:AuthenticateMixins

    def create_login_data(self,request:HttpRequest):
        credentials = self.check_body(request).copy()
        if all(key in credentials.keys() for key in self.auth_fields):
            user = authenticate(request, username=credentials['username'] , password=credentials['password'])
            if user :
                return self.get_new_token(user)
            else :
                raise AuthenticationFailed(f'credentials are not valid !')
        else :
            raise AttributeError(f'plase make sure you are passing ( {" , ".join(self.auth_fields)} ) in request body as json')
        
    def get_new_token(self,user:Optional[User])->dict:
        token:RefreshToken = RefreshToken.for_user(user)
        return self.get_data(user,token.access_token)

    def get_data(self,user:User ,token , *args , **kwargs):
        data:dict = self.user_serializer(user).data.copy()
        data.update({AUTH_COOKIE:f"{token}"})
        data.update({EXPIRE:datetime.utcfromtimestamp(token['exp']).isoformat()})
        return data

    def login(self,request:HttpRequest):
        user , token = self.auth_class(request)
        if all(var != None for var in [user , token]):
            return self.get_data(user,token)
        else :
            return self.create_login_data(request)

    def check_body(self , request:Request):
        try :
            return json.loads(request.body)
        except json.JSONDecodeError: ...
        return request.query_params.dict()


        