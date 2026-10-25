import json
import time
from datetime import datetime, timedelta

from django.db import connection
from django.http import StreamingHttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.utils.encoders import JSONEncoder

from .queries import snapshot


def _key(snap):
    latest = snap["latest"]
    return snap["unread"], (latest or {}).get("uuid")


def event_stream(user, token_exp, *, clock=datetime.now, sleep=time.sleep, poll=3, ping=15):
    """Yield SSE frames: a snapshot when unread/latest changed, a ping after `ping` s of silence.

    Ends once `clock() >= token_exp` so the client reconnects with a fresh token.
    """
    last_key = None
    last_frame = clock()
    while True:
        now = clock()
        snap = snapshot(user, now)
        key = _key(snap)
        if last_key is None or key != last_key:
            last_key = key
            last_frame = now
            yield f"event: snapshot\ndata: {json.dumps(snap, cls=JSONEncoder)}\n\n"
        elif (now - last_frame).total_seconds() >= ping:
            last_frame = now
            yield ": ping\n\n"
        connection.close()  # don't hold a DB connection while idle
        if clock() >= token_exp:
            return
        sleep(poll)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notification_stream(request):
    auth = request.auth
    try:
        token_exp = datetime.fromtimestamp(auth["exp"])
    except (TypeError, KeyError, ValueError):
        token_exp = datetime.now() + timedelta(hours=1)
    response = StreamingHttpResponse(event_stream(request.user, token_exp), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
