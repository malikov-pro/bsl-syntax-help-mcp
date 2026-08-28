from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

OPEN_PATHS = frozenset({"/health", "/ready", "/status", "/", "/favicon.ico"})


def _extract_bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def tokens_match(provided: str | None, expected: str) -> bool:
    if provided is None:
        return False
    left = provided.encode("utf-8")
    right = expected.encode("utf-8")
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in OPEN_PATHS:
            return await call_next(request)

        token = _extract_bearer(request.headers.get("authorization"))
        if path.startswith("/ingest") or path.startswith("/admin"):
            expected = settings.ingest_token
        elif path == "/mcp" or path.startswith("/mcp/"):
            expected = settings.mcp_token
        else:
            return await call_next(request)

        if not tokens_match(token, expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)
