"""FastAPI application entry point."""

from __future__ import annotations

import os
from uuid import uuid4
from typing import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.auth.routes import router as auth_router
from app.api.routes import router as api_router


app = FastAPI(title="AI-Driven Autonomous NoSQL Query Optimization Framework")
app.include_router(auth_router)
app.include_router(api_router)
_production = os.getenv("APP_ENV", "development") == "production"
_allowed_origins = [origin for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if origin]
_allowed_hosts = [host for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,api").split(",") if host]
if _production and (not _allowed_origins or "*" in _allowed_origins or not _allowed_hosts or "*" in _allowed_hosts):
    raise RuntimeError("Production requires explicit non-wildcard CORS origins and allowed hosts.")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
_log = structlog.get_logger("api")


@app.middleware("http")
async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Attach a request ID and return a secret-safe generic failure on unhandled errors."""
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    try:
        response = await call_next(request)
    except Exception:
        _log.exception("unhandled_request_error", request_id=request_id, service="api")
        return JSONResponse(status_code=500, content={"detail": "Internal server error.", "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    _log.info("request_complete", request_id=request_id, service="api", status_code=response.status_code)
    return response


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Report that the API process is alive."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    """Report that the Phase 1 API can accept requests."""
    return {"status": "ready"}
