from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings


class RequestGuardrailsMiddleware(BaseHTTPMiddleware):
    """Apply request-size, auth-rate, and browser security guardrails.

    The in-process limiter is a last line of defense. Cloud Armor should remain
    the network-level rate limiter for a multi-instance Cloud Run deployment.
    """

    def __init__(self, app):
        super().__init__(app)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _limited(self, key: str, limit: int, window: int) -> bool:
        now = monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= window:
                events.popleft()
            if len(events) >= limit:
                return True
            events.append(now)
            return False

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > settings.MAX_REQUEST_BYTES
        ):
            return JSONResponse(status_code=413, content={"detail": "Request body is too large"})

        if settings.RATE_LIMIT_ENABLED:
            client = request.client.host if request.client else "unknown"
            if request.url.path == "/api/auth/google" and self._limited(
                f"auth:{client}", settings.AUTH_RATE_LIMIT, 300
            ):
                return JSONResponse(
                    status_code=429, content={"detail": "Too many sign-in attempts"}
                )
            if request.url.path.startswith("/api/") and self._limited(
                f"api:{client}", settings.API_RATE_LIMIT, 60
            ):
                return JSONResponse(status_code=429, content={"detail": "Too many requests"})

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://accounts.google.com; "
            "connect-src 'self' https://accounts.google.com https://oauth2.googleapis.com; "
            "img-src 'self' data: https://*.googleusercontent.com; "
            "style-src 'self' 'unsafe-inline'; frame-src https://accounts.google.com; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if settings.ENV.lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
