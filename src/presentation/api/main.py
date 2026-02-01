"""
REST API entry point.

FastAPI application for programmatic access to the outreach system.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import structlog

from src.config import get_settings
from src.infrastructure.database import init_database, close_database
from src.infrastructure.ai import close_ai_provider

from .routes import (
    accounts_router,
    campaigns_router,
    proxies_router,
    stats_router,
    dialogues_router,
    premium_router,
)
from .middleware import APIKeyMiddleware, SecurityHeadersMiddleware, RateLimitMiddleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan handler."""
    # Startup
    await init_database()
    logger.info("API started")
    
    yield
    
    # Shutdown
    await close_ai_provider()
    await close_database()
    logger.info("API stopped")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    
    is_production = settings.environment == "production"
    app = FastAPI(
        title="Telegram Outreach API",
        description="API для управления системой Telegram Outreach",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if is_production else "/api/docs",
        redoc_url=None if is_production else "/api/redoc",
        openapi_url=None if is_production else "/api/openapi.json",
    )
    
    # CORS — use configured origins (default "*" for dev, restrict in production)
    cors_origins = [
        o.strip()
        for o in settings.security.cors_allowed_origins.split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Rate limiting (120 requests per minute per IP)
    app.add_middleware(RateLimitMiddleware, max_requests=120, window_seconds=60)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # API Key authentication
    app.add_middleware(APIKeyMiddleware)
    
    # Include routers
    app.include_router(accounts_router, prefix="/api/v1/accounts", tags=["Accounts"])
    app.include_router(campaigns_router, prefix="/api/v1/campaigns", tags=["Campaigns"])
    app.include_router(proxies_router, prefix="/api/v1/proxies", tags=["Proxies"])
    app.include_router(stats_router, prefix="/api/v1/stats", tags=["Statistics"])
    app.include_router(dialogues_router, prefix="/api/v1/dialogues", tags=["Dialogues"])
    app.include_router(premium_router, prefix="/api/v1/premium", tags=["Premium"])
    
    # Health check
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok"}
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception",
            path=request.url.path,
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.presentation.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
