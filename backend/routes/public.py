"""
Public (unauthenticated) endpoints for the VoxPilot landing page.

  GET  /public/demo-info        — returns the live demo phone number so the
                                   frontend never needs it hardcoded.
  POST /public/demo-request     — captures a callback lead (name + phone +
                                   optional note). No telephony is triggered;
                                   a DemoRequest row is written and the team
                                   reviews it via GET /admin/demo-requests.

Rate-limiting reuses the shared slowapi limiter from backend/services/limiter.py,
which is already wired into the FastAPI app in backend/app.py.
"""

import re
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.services.limiter import limiter
from backend.config.settings import settings
from backend.models import DemoRequest
from backend.utils.helpers import api_response, serialize_model

logger = logging.getLogger("public-router")
router = APIRouter(prefix="/public", tags=["Public"])

# Basic phone validation — digits, spaces, dashes, plus, parens; 7–15 digits total.
_PHONE_RE = re.compile(r"^\+?[\d\s\-().]{7,20}$")


def _valid_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return bool(_PHONE_RE.match(phone)) and 7 <= len(digits) <= 15


class DemoRequestPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=7, max_length=20)
    note: str | None = Field(default=None, max_length=1000)
    email: str | None = Field(default=None, max_length=255)


@router.get("/demo-info")
async def demo_info():
    """Return the live demo phone number for the landing page 'tap to call' card.

    The number comes from DEMO_PHONE_NUMBER in .env. If unset an empty string
    is returned — the frontend should show a 'coming soon' state in that case.
    """
    return api_response(
        success=True,
        message="Demo info fetched",
        data={"demo_phone_number": settings.DEMO_PHONE_NUMBER or ""},
    )


@router.post("/demo-request")
@limiter.limit("5/minute")
async def create_demo_request(
    request: Request,  # required by slowapi for IP key extraction
    payload: DemoRequestPayload,
    db: AsyncSession = Depends(get_db),
):
    """Capture a callback lead from the landing page.

    Writes a DemoRequest row (status='pending'). No call is placed — the team
    reviews leads via GET /admin/demo-requests and follows up manually.
    """
    phone = (payload.phone or "").strip()
    if not _valid_phone(phone):
        return api_response(
            success=False,
            message="Please enter a valid phone number.",
            status_code=400,
        )

    req = DemoRequest(
        name=payload.name.strip(),
        phone=phone,
        email=(payload.email or "").strip() or None,
        note=(payload.note or "").strip() or None,
        status="pending",
    )
    db.add(req)
    await db.commit()

    logger.info(f"Demo request captured: name={req.name} phone={req.phone}")
    return api_response(
        success=True,
        message="Thanks! We'll call you back shortly.",
        data=serialize_model(req),
    )
