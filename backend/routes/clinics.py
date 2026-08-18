from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.services import audit, whatsapp
from backend.services.limiter import limiter
from backend.routes.auth import get_current_user, require_non_staff
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


class WhatsAppVerify(BaseModel):
    """Credentials to check, plus the template settings saved alongside them.

    `access_token` may be omitted or blank to re-verify the token already stored —
    the dashboard never receives the token back, so it cannot echo it to us.
    """
    whatsapp_phone_number_id: Optional[str] = None
    whatsapp_access_token: Optional[str] = None
    whatsapp_template_lang: Optional[str] = None
    whatsapp_confirm_template: Optional[str] = None
    whatsapp_reminder_template: Optional[str] = None


# Changing either credential invalidates a previous check.
_WA_CREDENTIAL_FIELDS = ("whatsapp_phone_number_id", "whatsapp_access_token")


def _mask_secrets(data: dict) -> dict:
    """Never return the raw WhatsApp access token; expose only whether it's set."""
    if data is None:
        return data
    data["whatsapp_access_token_set"] = bool(data.get("whatsapp_access_token"))
    data["whatsapp_access_token"] = ""
    # Derived so the dashboard never has to interpret a timestamp to draw a badge.
    data["whatsapp_verified"] = bool(data.get("whatsapp_verified_at"))
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
    # require_non_staff, not get_current_user: StaffRoute already hides /setup from
    # staff in the dashboard, but the API was still open to them — and this payload
    # carries the AI's system prompt, the knowledge base and the WhatsApp access
    # token. A UI-only restriction is not a restriction.
    current_user: dict = Depends(require_non_staff),
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
        # A credential that changes here has not been checked against Meta, so any
        # earlier verification no longer describes what is stored. Enforced on this
        # route as well as on /whatsapp/verify, so the badge cannot go stale
        # whichever path writes the value.
        if key in _WA_CREDENTIAL_FIELDS and (value or "").strip() != (getattr(tenant, key) or ""):
            tenant.whatsapp_verified_at = None
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


@router.post("/whatsapp/verify")
@limiter.limit("6/minute")
async def verify_whatsapp(
    request: Request,  # required by slowapi for IP key extraction
    payload: WhatsAppVerify,
    # Same gate as PUT /settings: this both reads and writes the access token.
    current_user: dict = Depends(require_non_staff),
    db: AsyncSession = Depends(get_db),
):
    """Check WhatsApp credentials against the Cloud API, and save them if they pass.

    Verify and save are one operation on purpose. Saving first would leave the tenant
    with stored credentials that silently do not work, which is the state this whole
    endpoint exists to make visible. Rate limited because it reaches an external API
    on demand.

    Only these five fields are touched, so it cannot disturb the prompts, knowledge
    base or voice settings that share PUT /settings.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    result = await db.execute(select(Tenant).where(Tenant.id == clinic_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        return api_response(success=False, message="Clinic settings not found", status_code=404)

    phone_id = (payload.whatsapp_phone_number_id or "").strip()
    # Blank means "re-check what is already stored" — the dashboard cannot send back
    # a token it was never given.
    token = (payload.whatsapp_access_token or "").strip() or (tenant.whatsapp_access_token or "")

    if not phone_id.isdigit() or not (10 <= len(phone_id) <= 20):
        return api_response(
            success=False,
            message="Phone Number ID should be the 15-digit numeric ID from Meta, not the phone number itself.",
            status_code=400,
        )

    ok, error, info = await whatsapp.verify_credentials(phone_id, token)
    if not ok:
        # Nothing is persisted on failure, so a bad paste cannot break working config.
        return api_response(success=False, message=error, status_code=400)

    tenant.whatsapp_phone_number_id = phone_id
    tenant.whatsapp_access_token = token
    if payload.whatsapp_template_lang is not None:
        tenant.whatsapp_template_lang = payload.whatsapp_template_lang.strip()
    if payload.whatsapp_confirm_template is not None:
        tenant.whatsapp_confirm_template = payload.whatsapp_confirm_template.strip()
    if payload.whatsapp_reminder_template is not None:
        tenant.whatsapp_reminder_template = payload.whatsapp_reminder_template.strip()
    tenant.whatsapp_verified_at = datetime.utcnow()
    await db.commit()

    # Field names only, never the token — same rule as PUT /settings.
    await audit.record(
        audit.SETTINGS_UPDATED, actor=current_user, clinic_id=clinic_id,
        target_type="tenant", target_id=clinic_id,
        detail={"fields": ["whatsapp_verified"], "whatsapp_phone_number_id": phone_id},
        request=request,
    )

    data = _mask_secrets(serialize_model(tenant))
    data["whatsapp_number_info"] = info
    return api_response(success=True, message="WhatsApp connected.", data=data)


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
