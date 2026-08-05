import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.services import events
from backend.services.db import connect_to_db, close_db_connection, get_sessionmaker
from backend.services.limiter import limiter
from backend.middlewares.security import (
    SecurityHeadersMiddleware,
    enforce_production_config,
)
from backend.jobs.reminder_worker import reminder_loop
from backend.jobs.call_sweeper import call_sweeper_loop
from backend.routes.auth import router as auth_router
from backend.routes.calls import router as calls_router
from backend.routes.patients import router as patients_router
from backend.routes.appointments import router as appointments_router
from backend.routes.clinics import router as clinics_router
from backend.routes.phone_numbers import router as phone_numbers_router
from backend.routes.stats import router as stats_router
from backend.routes.templates import router as templates_router
from backend.routes.billing import router as billing_router
from backend.routes.admin import router as admin_router
from backend.routes.messages import router as messages_router
from backend.websocket.handler import router as ws_router
from backend.config.settings import settings

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("app-bootstrap")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect first, then audit the configuration. Some checks describe the real
    # connection (whether the database's certificate is actually being verified,
    # whether rate-limit storage is shared) and would be meaningless beforehand.
    # This still runs before any request is served, which is the point.
    await connect_to_db()
    # Cross-process notification bus. Without it, a dashboard connected to replica A
    # never hears an event published by replica B.
    await events.start_event_bridge()
    # Fail fast on insecure configuration BEFORE serving traffic. In production a
    # default JWT secret or wildcard CORS aborts the boot; elsewhere it warns.
    enforce_production_config()
    # Both workers self-elect via a Postgres advisory lock, so starting them in every
    # replica is safe — exactly one process actually runs each job. Critical for the
    # reminder worker: two senders means customers get duplicate WhatsApp messages.
    background_tasks = [
        asyncio.create_task(reminder_loop()),
        # Closes call_logs rows whose "call ended" report never arrived, so a
        # crashed agent cannot leave a customer with calls that never end.
        asyncio.create_task(call_sweeper_loop()),
    ]
    yield
    # Shutdown: stop the workers, then close the connection.
    for task in background_tasks:
        task.cancel()
    for task in background_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    await events.stop_event_bridge()
    await close_db_connection()

app = FastAPI(
    title="Clarivo - Voice Receptionist",
    description="Multi-tenant Voice AI receptionist for businesses across industries (clinics, real estate, hospitality, salons, services, and more).",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Hardening headers on every response (HSTS only outside local dev).
app.add_middleware(
    SecurityHeadersMiddleware,
    hsts=(settings.ENV or "").strip().lower() in ("production", "prod", "staging"),
)

# CORS configuration — restricted to configured dashboard origins.
_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST Routing
app.include_router(auth_router, prefix="/api")
app.include_router(calls_router, prefix="/api")
app.include_router(patients_router, prefix="/api")
app.include_router(appointments_router, prefix="/api")
app.include_router(clinics_router, prefix="/api")
app.include_router(phone_numbers_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(messages_router, prefix="/api")

# Mount Websocket Routing
app.include_router(ws_router)

@app.get("/")
async def root():
    return {
        "success": True,
        "message": "Clarivo Receptionist API is running",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
async def health():
    """Liveness + readiness probe for load balancers and orchestrators.

    `/` only proves the process is up; it never touches the database, so a
    backend that had lost its DB still looked healthy. This actually round-trips
    a query and returns 503 when the database is unreachable, which is what a
    rolling deploy needs in order not to shift traffic onto a broken instance.
    """
    checks = {"api": "ok", "database": "unknown"}
    Session = get_sessionmaker()
    if Session is None:
        checks["database"] = "not_configured"
    else:
        try:
            async with Session() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:  # noqa: BLE001 — report, don't leak details
            logger.error(f"Health check DB probe failed: {e}")
            checks["database"] = "error"

    healthy = checks["database"] == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "healthy" if healthy else "degraded", "checks": checks,
                 "version": "1.0.0"},
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
