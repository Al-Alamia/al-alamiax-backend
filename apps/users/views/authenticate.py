from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework.status import  HTTP_401_UNAUTHORIZED , HTTP_200_OK
from rest_framework.request import Request
from apps.users.auth import Login
from auth.constants import AUTH_COOKIE
from rest_framework.status import HTTP_200_OK,HTTP_401_UNAUTHORIZED
from apps.users.models import FingerPrintID
from apps.users.serializers import FingerPrintIDSerializer


@api_view(["POST","GET"])
def login(request: Request):
    login_class = Login()
    try :
        data = login_class.login(request)
        uuid = data.get("uuid",None)
        is_superuser = data.get("is_superuser",False)
        if is_superuser : 
            data.update({"unique_id":"SuperUser"})
        elif uuid :
            finger = FingerPrintID.objects.filter(user__uuid=uuid , unique_id=request.query_params.get("unique_id",request.data.get("unique_id",None))).first()
            if not finger :
                raise NotImplementedError("No Devices ID added Please add one !")
            data.update({"unique_id":FingerPrintIDSerializer(finger).data})
        else :
            raise NotImplementedError

        status = HTTP_200_OK
        response = Response(data,status)
        response.set_cookie(AUTH_COOKIE , data[AUTH_COOKIE])
    except Exception as e :
        data = {
            "message" : str(e),
            "type" : str(e.__class__.__name__)
        }
        status = HTTP_401_UNAUTHORIZED
        response = Response(data,status)
    return response

@api_view(["GET" , "POST"])
def logout(request: Request):
    response = Response({"message":"Logout successfully"})
    response.delete_cookie(AUTH_COOKIE)
    return response
