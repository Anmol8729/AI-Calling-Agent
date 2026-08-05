from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.services import audit
from backend.routes.auth import get_current_user
from backend.models import Tenant
from backend.utils.helpers import api_response, serialize_model, to_uuid

router = APIRouter(prefix="/clinics", tags=["Clinic Profile"])


class ClinicSettingsUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    # "time" (fixed slots) or "token" (daily queue number). The queue counters
    # themselves are managed only via the /appointments/queue endpoints.
    booking_mode: Optional[str] = None
    notify_email: Optional[str] = None
    did: Optional[str] = None
    system_prompt: Optional[str] = None
    initial_greeting: Optional[str] = None
    knowledge_base: Optional[str] = None
    voice: Optional[str] = None
    language: Optional[str] = None
    llm_model: Optional[str] = None
    whatsapp_phone_number_id: Optional[str] = None
    whatsapp_access_token: Optional[str] = None
    whatsapp_template_lang: Optional[str] = None
    whatsapp_confirm_template: Optional[str] = None
    whatsapp_reminder_template: Optional[str] = None


def _mask_secrets(data: dict) -> dict:
    """Never return the raw WhatsApp access token; expose only whether it's set."""
    if data is None:
        return data
    data["whatsapp_access_token_set"] = bool(data.get("whatsapp_access_token"))
    data["whatsapp_access_token"] = ""
    return data


@router.get("/settings")
async def get_settings(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    result = await db.execute(select(Tenant).where(Tenant.id == clinic_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return api_response(success=False, message="Clinic settings not found", status_code=404)

    return api_response(
        success=True,
        message="Clinic settings fetched successfully",
        data=_mask_secrets(serialize_model(tenant)),
    )


@router.put("/settings")
async def update_settings(
    payload: ClinicSettingsUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    # model_dump, not the deprecated Pydantic v1 .dict().
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        return api_response(success=False, message="No settings data provided for update", status_code=400)

    result = await db.execute(select(Tenant).where(Tenant.id == clinic_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return api_response(success=False, message="Clinic settings not found", status_code=404)

    for key, value in update_data.items():
        # Don't wipe the stored WhatsApp token when the field is left blank
        # (the dashboard sends blank to mean "keep the existing token").
        if key == "whatsapp_access_token" and not (value or "").strip():
            continue
        setattr(tenant, key, value)
    await db.commit()

    # Record WHICH settings changed, never their values — this payload can carry a
    # WhatsApp access token and the AI's system prompt.
    await audit.record(
        audit.SETTINGS_UPDATED, actor=current_user, clinic_id=clinic_id,
        target_type="tenant", target_id=clinic_id,
        detail={"fields": sorted(update_data.keys())},
        request=request,
    )

    return api_response(
        success=True,
        message="Clinic settings updated successfully",
        data=_mask_secrets(serialize_model(tenant)),
    )


@router.get("/activity")
async def clinic_activity(
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """This tenant's own activity timeline, newest first.

    Scoped to the caller's clinic, so one client can never read another's trail.
    Read-only: audit rows are append-only and cannot be edited through the app.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)
    items = await audit.list_for_clinic(clinic_id, limit=limit, offset=offset)
    return api_response(success=True, message="Activity fetched", data={"items": items})
