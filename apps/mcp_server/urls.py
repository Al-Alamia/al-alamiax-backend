from django.urls import path

from . import protocol, views
from .oauth import authorize, metadata, registration, token

urlpatterns = [
    path(".well-known/oauth-protected-resource", metadata.protected_resource_metadata),
    path(".well-known/oauth-protected-resource/mcp", metadata.protected_resource_metadata),
    path(".well-known/oauth-authorization-server", metadata.authorization_server_metadata),
    path("oauth/register", registration.register),
    path("oauth/authorize", authorize.authorize),
    path("oauth/token", token.token),
    path("mcp", protocol.mcp_endpoint),
    path("api/mcp/oauth/consent", authorize.consent),
    path("api/mcp/grants", views.grants),
    path("api/mcp/grants/<uuid:grant_uuid>", views.revoke),
    path("api/mcp/access", views.access),
]
