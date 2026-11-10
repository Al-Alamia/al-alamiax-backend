from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce

from apps.mcp_server.models import (
    McpCallLog, OAuthAuthorizationCode, OAuthClient, OAuthGrant, OAuthToken)

CODE_RETENTION = timedelta(days=1)
TOKEN_RETENTION = timedelta(days=7)
CALL_LOG_RETENTION = timedelta(days=180)
CLIENT_RETENTION = timedelta(days=30)


def prune(now: datetime) -> dict:
    """Delete expired OAuth artifacts and old call logs; returns counts per kind."""
    with transaction.atomic():
        codes = OAuthAuthorizationCode.objects.filter(
            expires_at__lt=now - CODE_RETENTION).delete()[0]
        cutoff = now - TOKEN_RETENTION
        tokens = OAuthToken.objects.filter(
            Q(expires_at__lt=cutoff) | Q(revoked_at__lt=cutoff)).delete()[0]
        call_logs = McpCallLog.objects.filter(
            created_at__lt=now - CALL_LOG_RETENTION).delete()[0]
        active = OAuthGrant.objects.active().values("client_id")
        # Grants/tokens/codes of a deleted client cascade away; only clients are counted.
        stale = (OAuthClient.objects.exclude(pk__in=active)
                 .annotate(last_seen=Coalesce("last_used_at", "created_at"))
                 .filter(last_seen__lt=now - CLIENT_RETENTION))
        clients = OAuthClient.objects.filter(pk__in=list(stale.values_list("pk", flat=True))
                                             ).delete()[1].get(OAuthClient._meta.label, 0)
    return {"codes": codes, "tokens": tokens, "call_logs": call_logs, "clients": clients}
