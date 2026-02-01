"""API middleware.

- API key authentication (X-API-Key)
- Rate limiting (in-memory sliding window)
- Security headers
- Request logging

The project uses a single API key configured via Settings.security.api_key.
"""

from __future__ import annotations

import secrets
import time
from collections import defaultdict
from typing import Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import get_settings

logger = structlog.get_logger(__name__)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware for API key authentication."""

    SKIP_PATHS = {
        "/health",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
    }

    SKIP_PREFIXES = (
        "/api/v1/premium/",  # Public payment pages
    )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip authentication for docs/health.
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        # Skip authentication for premium payment pages
        if request.url.path.startswith(self.SKIP_PREFIXES):
            return await call_next(request)

        settings = get_settings()
        configured = settings.security.api_key.get_secret_value() if settings.security.api_key else ""

        # Require API key to be configured. Reject all requests if missing.
        if not configured:
            logger.error("API key not configured. Set SECURITY_API_KEY in environment.")
            return JSONResponse(
                status_code=503,
                content={"detail": "API key not configured on server"},
            )

        provided = request.headers.get("X-API-Key") or ""
        if not provided:
            return JSONResponse(status_code=401, content={"detail": "Missing API key"})

        if not secrets.compare_digest(provided, configured):
            return JSONResponse(status_code=401, content={"detail": "Invalid API key"})

        request.state.api_key = provided
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory sliding window rate limiter per client IP.

    Limits each IP to ``max_requests`` within ``window_seconds``.
    Stateless across restarts (acceptable for single-instance deployments).
    """

    def __init__(self, app, max_requests: int = 120, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window_seconds

        # Prune expired entries
        timestamps = self._hits[client_ip]
        self._hits[client_ip] = [t for t in timestamps if t > cutoff]

        if len(self._hits[client_ip]) >= self.max_requests:
            logger.warning("Rate limit exceeded", client_ip=client_ip)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
                headers={"Retry-After": str(self.window_seconds)},
            )

        self._hits[client_ip].append(now)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request/response logging."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        logger.info(
            "API request completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration * 1000, 2),
        )
        return response
