from rest_framework.response import Response


def error(message: str, type: str, status: int) -> Response:
    return Response({"message": message, "type": type}, status=status)
