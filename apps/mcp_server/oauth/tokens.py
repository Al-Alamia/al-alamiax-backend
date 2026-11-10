import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

from django.db import transaction

from apps.mcp_server.eligibility import is_eligible
from apps.mcp_server.models import OAuthClient, OAuthToken
from apps.mcp_server.oauth.errors import OAuthError

ACCESS_PREFIX = "amx_at_"
REFRESH_PREFIX = "amx_rt_"
ACCESS_TTL = 3600
REFRESH_TTL = timedelta(days=30)


def _now() -> datetime:
    return datetime.now()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_pair(grant, code=None) -> dict:
    now = _now()
    access = ACCESS_PREFIX + secrets.token_urlsafe(32)
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
    OAuthToken.objects.create(
        grant=grant, code=code, kind=OAuthToken.KIND_ACCESS, token_hash=hash_token(access),
        expires_at=now + timedelta(seconds=ACCESS_TTL))
    OAuthToken.objects.create(
        grant=grant, code=code, kind=OAuthToken.KIND_REFRESH, token_hash=hash_token(refresh),
        expires_at=now + REFRESH_TTL)
    return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL,
            "refresh_token": refresh, "scope": "mcp"}


def resolve_access(raw: str) -> Optional[OAuthToken]:
    if not raw:
        return None
    token = (OAuthToken.objects.select_related("grant__user", "grant__client")
             .filter(token_hash=hash_token(raw), kind=OAuthToken.KIND_ACCESS).first())
    if token is None or token.revoked_at is not None or token.expires_at <= _now():
        return None
    grant = token.grant
    if grant.revoked_at is not None or not is_eligible(grant.user):
        return None
    return token


def revoke_grant(grant, by=None) -> None:
    now = _now()
    grant.revoked_at = now
    grant.revoked_by = by
    grant.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
    grant.tokens.filter(revoked_at__isnull=True).update(revoked_at=now)


def rotate_refresh(raw: str, client: OAuthClient) -> dict:
    invalid = OAuthError("invalid_grant", "Invalid refresh token")
    token = (OAuthToken.objects.select_related("grant__user")
             .filter(token_hash=hash_token(raw or ""), kind=OAuthToken.KIND_REFRESH).first())
    if token is None:
        raise invalid
    grant = token.grant
    if grant.client_id != client.pk:
        raise invalid
    if token.used_at is not None:
        revoke_grant(grant)
        raise invalid
    if (token.revoked_at is not None or token.expires_at <= _now()
            or grant.revoked_at is not None or not is_eligible(grant.user)):
        raise invalid
    now = _now()
    with transaction.atomic():
        claimed = OAuthToken.objects.filter(
            pk=token.pk, used_at__isnull=True, revoked_at__isnull=True).update(used_at=now)
        if claimed:
            grant.last_used_at = now
            grant.save(update_fields=["last_used_at", "updated_at"])
            return issue_pair(grant, code=token.code)
    # Lost the compare-and-set: a concurrent request already used this token.
    revoke_grant(grant)
    raise invalid
