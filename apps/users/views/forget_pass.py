from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework.status import  HTTP_404_NOT_FOUND , HTTP_200_OK
from rest_framework.request import Request
from apps.users.models import User
from utils.telegram import sendTMessage

@api_view(["POST"])
def forget_password(request: Request):
    username = request.query_params.get("username")
    try :
        user:User = User.objects.get(username=username)
        tm_id = user.profile.telegram_id
        data = {
            "message" : "Error not sended"
        }

        status = HTTP_404_NOT_FOUND
        if tm_id :
            response = sendTMessage(f"""
Hello {username} ,\nPassword is : {user._password}\n\nfor security please don't tell any one this password\n
            """,tm_id)

            if not response.ok:
                data = {
                    "message" : "Check your Telegram to show your password"
                }

                status = HTTP_200_OK
        response = Response(data,status)
    except Exception as e :
        data = {
            "message" : str(e),
            "type" : str(e.__class__.__name__)
        }
        status = HTTP_404_NOT_FOUND
        response = Response(data,status)
    return response

