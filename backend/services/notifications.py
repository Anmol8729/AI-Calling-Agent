"""
Outbound alert emails to the business (e.g. when the AI books an appointment).

Kept separate from request/websocket code so it can be fired best-effort from
the live-call path without blocking or ever raising. Recipients are the tenant's
`notify_email` if set, otherwise the emails of the users in that clinic.
"""

import asyncio
import logging

from sqlalchemy import select

from backend.services.db import get_sessionmaker
from backend.services.email import send_email
from backend.services.whatsapp import send_appointment_confirmation, resolve_config
from backend.services import repository
from backend.config.settings import settings
from backend.models import Tenant, User
from backend.utils.helpers import to_uuid, serialize_model

logger = logging.getLogger("notifications")


async def send_customer_confirmation(clinic_id, phone, name, when):
    """Best-effort WhatsApp appointment confirmation to the customer, sent from
    the tenant's own WhatsApp config (or the platform fallback). Never raises."""
    try:
        if not phone:
            return
        Session = get_sessionmaker()
        cid = to_uuid(clinic_id)
        if Session is None or cid is None:
            return
        async with Session() as session:
            tenant = (await session.execute(select(Tenant).where(Tenant.id == cid))).scalar_one_or_none()
            tdict = serialize_model(tenant)  # serialize inside the session
        config = resolve_config(tdict)
        if not config:
            return
        business = (tdict or {}).get("name") or ""
        ok = await send_appointment_confirmation(config, phone, name, business, when)
        preview = f"Confirmation to {name or 'customer'} — {business} on {when or ''}".strip()
        await repository.log_whatsapp_message(
            clinic_id, phone, "confirmation", config.get("confirm_template"),
            preview, "sent" if ok else "failed",
        )
    except Exception as e:
        logger.warning(f"send_customer_confirmation failed: {e}")


async def _recipients(session, clinic_id):
    tenant = (await session.execute(select(Tenant).where(Tenant.id == clinic_id))).scalar_one_or_none()
    if tenant is None:
        return [], None
    if tenant.notify_email and tenant.notify_email.strip():
        return [tenant.notify_email.strip()], tenant.name
    rows = (await session.execute(select(User.email).where(User.clinic_id == clinic_id))).all()
    emails = [r[0] for r in rows if r and r[0]]
    return emails, tenant.name


async def notify_new_appointment(clinic_id, patient_name, when, reason):
    """Best-effort alert when the AI books an appointment. Never raises."""
    try:
        Session = get_sessionmaker()
        cid = to_uuid(clinic_id)
        if Session is None or cid is None:
            return
        async with Session() as session:
            recipients, business = await _recipients(session, cid)
        if not recipients:
            return
        subject = f"New booking: {patient_name or 'a caller'}"
        text = (
            "Your AI receptionist just booked an appointment.\n\n"
            f"Name:   {patient_name or '-'}\n"
            f"When:   {when or '-'}\n"
            f"Reason: {reason or '-'}\n\n"
            f"— {business or 'Clarivo'}"
        )
        for email in recipients:
            try:
                await asyncio.to_thread(send_email, email, subject, text)
            except Exception as e:
                logger.warning(f"Booking alert email failed for {email}: {e}")
    except Exception as e:
        logger.warning(f"notify_new_appointment failed: {e}")
