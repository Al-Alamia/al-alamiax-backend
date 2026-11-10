from django.conf import settings
from django.db import models

from core.models import BaseModel


class OAuthClient(BaseModel):
    client_id = models.CharField(max_length=64, unique=True)
    client_name = models.CharField(max_length=100, default="AI client")
    redirect_uris = models.JSONField(default=list)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.client_name


class OAuthAuthorizationCode(BaseModel):
    """Pending authorization request; becomes a code once a user approves."""
    request_id = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="codes")
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    state = models.TextField(blank=True, default="")
    resource = models.TextField(blank=True, default="")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.CASCADE, related_name="+")
    code_hash = models.CharField(max_length=64, unique=True, null=True, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class OAuthGrantQuerySet(models.QuerySet):
    def active(self):
        return self.filter(revoked_at__isnull=True)


class OAuthGrant(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="mcp_grants")
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="grants")
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    objects = OAuthGrantQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "client"],
                                    condition=models.Q(revoked_at__isnull=True),
                                    name="uniq_active_mcp_grant"),
        ]


class OAuthToken(BaseModel):
    KIND_ACCESS = "access"
    KIND_REFRESH = "refresh"
    KIND_CHOICES = [(KIND_ACCESS, "Access"), (KIND_REFRESH, "Refresh")]

    grant = models.ForeignKey(OAuthGrant, on_delete=models.CASCADE, related_name="tokens")
    code = models.ForeignKey(OAuthAuthorizationCode, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="tokens")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class McpCallLog(BaseModel):
    grant = models.ForeignKey(OAuthGrant, null=True, on_delete=models.SET_NULL, related_name="calls")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    tool = models.CharField(max_length=100)
    arguments = models.JSONField(default=dict, blank=True)
    ok = models.BooleanField(default=True)
    error_type = models.CharField(max_length=100, blank=True, default="")
    duration_ms = models.IntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["user", "created_at"])]
