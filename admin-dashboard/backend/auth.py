"""Authentication middleware — Cloudflare Access + API key."""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def _get_allowed_emails():
    """Read ALLOWED_EMAILS from env at call time (not import time).

    This ensures .env is loaded before we read, regardless of import order.
    """
    return {
        e.strip().lower()
        for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
        if e.strip()
    }


def _get_api_key():
    return os.environ.get("DASHBOARD_API_KEY")

PUBLIC_PATHS = {"/api/health"}
LOCALHOSTS = {"localhost", "127.0.0.1", "::1"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Require authentication for all /api/ endpoints (except health).

    Auth methods (any one grants access):
    1. Cloudflare Access: Cf-Access-Authenticated-User-Email header
       (set by Cloudflare tunnel — cannot be spoofed since only
       cloudflared can reach localhost:8000)
    2. API key: X-API-Key header or ?api_key query param
    3. Non-API paths (frontend static files) are always allowed
    """

    async def dispatch(self, request, call_next):
        path = request.url.path
        hostname = (request.url.hostname or "").lower()

        if path in PUBLIC_PATHS:
            return await call_next(request)

        if hostname in LOCALHOSTS:
            return await call_next(request)

        # 1. Cloudflare Access email header (set by Cloudflare tunnel)
        email = request.headers.get("cf-access-authenticated-user-email")
        if email:
            if email.lower() in _get_allowed_emails():
                return await call_next(request)
            return JSONResponse(
                status_code=403,
                content={"detail": f"Access denied. {email} is not authorized."},
            )

        # 2. Local/tunnel request without email — if coming through
        #    Cloudflare (has cf-connecting-ip), Access already verified
        if request.headers.get("cf-connecting-ip"):
            return await call_next(request)

        # 3. Local dev — allow frontend, gate API
        if not path.startswith("/api/"):
            return await call_next(request)

        # 4. API key auth (for agents, scripts, etc.)
        api_key = request.headers.get("x-api-key") or request.query_params.get("api_key")
        configured_key = _get_api_key()
        if configured_key and api_key == configured_key:
            return await call_next(request)
        if api_key:
            return JSONResponse(status_code=403, content={"detail": "Invalid API key"})

        return JSONResponse(status_code=403, content={"detail": "Authentication required"})
