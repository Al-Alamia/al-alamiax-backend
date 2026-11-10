from django.urls import path

from .oauth import authorize, metadata, registration

urlpatterns = [
    path(".well-known/oauth-protected-resource", metadata.protected_resource_metadata),
    path(".well-known/oauth-protected-resource/mcp", metadata.protected_resource_metadata),
    path(".well-known/oauth-authorization-server", metadata.authorization_server_metadata),
    path("oauth/register", registration.register),
    path("oauth/authorize", authorize.authorize),
    path("api/mcp/oauth/consent", authorize.consent),
]
