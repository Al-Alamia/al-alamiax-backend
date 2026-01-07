from apps.users.AuthenticationClasses import BodyAuthentication , HeaderAuthentication , CookieAuthentication
from auth.mixin import AuthenticateMixins , LoginMixins
from apps.users.serializers import UserSerializer

class AuthenticateUser(AuthenticateMixins):
    auth_classes = [
        CookieAuthentication ,
        HeaderAuthentication ,
        BodyAuthentication  , 
    ]


class Login(LoginMixins):
    auth_class = AuthenticateUser
    user_serializer =  UserSerializer
