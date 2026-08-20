"""FastAPI application entry point."""

from fastapi import FastAPI

from app.auth.routes import router as auth_router


app = FastAPI(title="AI-Driven Autonomous NoSQL Query Optimization Framework")
app.include_router(auth_router)


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Report that the API process is alive."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready() -> dict[str, str]:
    """Report that the Phase 1 API can accept requests."""
    return {"status": "ready"}
