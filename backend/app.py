import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.services.db import connect_to_db, close_db_connection
from backend.services.limiter import limiter
from backend.jobs.reminder_worker import reminder_loop
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
from backend.routes.public import router as public_router
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
    # Startup: connect to the DB and launch the appointment-reminder worker.
    await connect_to_db()
    reminder_task = asyncio.create_task(reminder_loop())
    yield
    # Shutdown: stop the worker and close the connection.
    reminder_task.cancel()
    try:
        await reminder_task
    except asyncio.CancelledError:
        pass
    await close_db_connection()

app = FastAPI(
    title="VoxPilot AI - Voice Receptionist",
    description="Multi-tenant Voice AI receptionist for businesses across industries (clinics, real estate, hospitality, salons, services, and more).",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
app.include_router(public_router, prefix="/api")

# Mount Websocket Routing
app.include_router(ws_router)

@app.get("/")
async def root():
    return {
        "success": True,
        "message": "VoxPilot AI Receptionist API is running",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
