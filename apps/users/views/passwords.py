from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND

from apps.users.models import User
from permissions.users import IsSuperUser, IsOwner, IsManager, IsHR

MIN_PASSWORD_LENGTH = 6


def _invalid_new_password(value):
    if not isinstance(value, str) or len(value) < MIN_PASSWORD_LENGTH:
        return f"New password must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    if not old_password or not new_password:
        return Response({"message": "old_password and new_password are required"}, HTTP_400_BAD_REQUEST)
    if not request.user.check_password(old_password):
        return Response({"message": "Old password is incorrect"}, HTTP_400_BAD_REQUEST)
    if request.user.check_password(new_password):
        return Response({"message": "New password must differ from the current password",
                         "type": "same_password"}, HTTP_400_BAD_REQUEST)
    error = _invalid_new_password(new_password)
    if error:
        return Response({"message": error}, HTTP_400_BAD_REQUEST)
    request.user.set_password(new_password)
    request.user.must_change_password = False
    request.user.save()
    return Response({"message": "Password changed successfully"}, HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsSuperUser | IsOwner | IsManager | IsHR])
def set_password(request, uuid):
    user = User.objects.filter(uuid=uuid).first()
    if not user:
        return Response({"message": "User not found"}, HTTP_404_NOT_FOUND)
    caller = request.user
    if user.is_superuser and not caller.is_superuser:
        return Response({"message": "You are not allowed to reset this user's password"}, HTTP_403_FORBIDDEN)
    if user.role == "OWNER" and not (caller.is_superuser or caller.role == "OWNER"):
        return Response({"message": "You are not allowed to reset this user's password"}, HTTP_403_FORBIDDEN)
    new_password = request.data.get("new_password")
    error = _invalid_new_password(new_password)
    if error:
        return Response({"message": error}, HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.must_change_password = True
    user.save()
    # Revoke every outstanding refresh token so existing sessions end.
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)
    return Response({"message": "Password updated successfully"}, HTTP_200_OK)
