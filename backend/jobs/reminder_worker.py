"""
Background reminder worker.

Periodically finds scheduled appointments whose start is within the reminder
lead window and hasn't been reminded yet, sends a WhatsApp reminder, and marks
it sent. Runs as an asyncio task started in the app lifespan (no external
scheduler/Celery). No-op while WhatsApp is unconfigured.

Note: `appointment_at` is naive local wall-time, so we compare against
datetime.now() (server local).

Multiple replicas are now safe: the loop runs under a Postgres advisory lock so
exactly one process sends. Without it, two replicas would both see the same
appointment with `reminder_sent = False` and both send — the customer receives the
reminder twice, because the flag is only written after sending.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from backend.services.db import get_sessionmaker
from backend.services.job_lock import run_as_single_owner
from backend.services.whatsapp import send_appointment_reminder, resolve_config
from backend.services import repository
from backend.config.settings import settings
from backend.models import Appointment, Tenant
from backend.utils.helpers import serialize_model

logger = logging.getLogger("reminder-worker")


async def _run_once():
    Session = get_sessionmaker()
    if Session is None:
        return
    now = datetime.now()  # naive local, matching the appointment_at convention
    horizon = now + timedelta(minutes=settings.WHATSAPP_REMINDER_LEAD_MIN)
    async with Session() as session:
        rows = (await session.execute(
            select(Appointment, Tenant)
            .join(Tenant, Tenant.id == Appointment.clinic_id)
            .where(
                Appointment.status == "scheduled",
                Appointment.reminder_sent.is_(False),
                Appointment.appointment_at.isnot(None),
                Appointment.phone.isnot(None),
                Appointment.appointment_at > now,
                Appointment.appointment_at <= horizon,
            )
        )).all()
        for appt, tenant in rows:
            config = resolve_config(serialize_model(tenant))
            if not config:
                continue  # this tenant has no WhatsApp configured
            when = appt.appointment_at.strftime("%d %b %Y, %I:%M %p")
            try:
                ok = await send_appointment_reminder(config, appt.phone, appt.patient_name, tenant.name or "", when)
            except Exception as e:
                logger.warning(f"Reminder send failed for {appt.id}: {e}")
                ok = False
            preview = f"Reminder to {appt.patient_name or 'customer'} — {tenant.name or ''} on {when}".strip()
            await repository.log_whatsapp_message(
                appt.clinic_id, appt.phone, "reminder", config.get("reminder_template"),
                preview, "sent" if ok else "failed",
            )
            if ok:
                appt.reminder_sent = True
        await session.commit()


async def reminder_loop():
    """Run reminder checks on an interval, on exactly ONE process.

    Every replica starts this loop, but a Postgres advisory lock means only one of
    them sends. This is not an optimisation: two replicas would both read the same
    appointment with `reminder_sent = False` and both send, so the customer gets the
    same WhatsApp message twice. The flag is only written after sending, so nothing
    else prevents it.

    If the owning process dies, its session ends, Postgres releases the lock, and
    another replica takes over on its next check.
    """
    interval = max(int(settings.WHATSAPP_REMINDER_INTERVAL_SEC or 300), 30)
    logger.info(
        f"Reminder worker starting (interval={interval}s, lead={settings.WHATSAPP_REMINDER_LEAD_MIN}min)."
    )
    await run_as_single_owner("whatsapp_reminders", _run_once, interval=interval)
