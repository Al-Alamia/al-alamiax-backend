from django.conf import settings


def public_base(request) -> str:
    configured = getattr(settings, "MCP_PUBLIC_URL", "") or ""
    if configured:
        return configured.rstrip("/")
    return request.build_absolute_uri("/").rstrip("/")


def resource_url(request) -> str:
    return public_base(request) + "/mcp"


def frontend_base(request) -> str:
    configured = getattr(settings, "MCP_FRONTEND_URL", "") or ""
    return configured.rstrip("/") if configured else public_base(request)
