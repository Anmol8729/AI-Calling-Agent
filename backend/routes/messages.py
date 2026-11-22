"""
WhatsApp message log — read-only feed of confirmations + reminders the system
has sent for the logged-in tenant.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.routes.auth import get_current_user
from backend.models import WhatsAppMessage
from backend.utils.helpers import api_response, serialize_models, to_uuid

router = APIRouter(prefix="/messages", tags=["Messages"])


@router.get("/whatsapp")
async def whatsapp_messages(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    from backend.services.demo_data import get_demo_messages, DEMO_CLINIC_ID
    if db is None or str(clinic_id) == DEMO_CLINIC_ID:
        return api_response(
            success=True,
            message="WhatsApp messages fetched",
            data=get_demo_messages(),
        )

    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    rows = (await db.execute(
        select(WhatsAppMessage)
        .where(WhatsAppMessage.clinic_id == clinic_id)
        .order_by(WhatsAppMessage.created_at.desc())
        .limit(100)
    )).scalars().all()
    return api_response(
        success=True,
        message="WhatsApp messages fetched",
        data=serialize_models(rows),
    )
