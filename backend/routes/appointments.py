import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.services import repository, notifications, events, audit
from backend.routes.auth import get_current_user, require_non_staff
from backend.models import Appointment, Tenant
from backend.schemas.patient import AppointmentCreate
from backend.utils.helpers import api_response, serialize_model, serialize_models, to_uuid

router = APIRouter(prefix="/appointments", tags=["Appointments"])


class AppointmentReschedule(BaseModel):
    appointment_at: datetime
    duration_min: int = 30


class QueueSet(BaseModel):
    # "Now serving" number to set for today (0 = reset / nobody being served yet).
    number: int = 0


@router.get("/")
async def list_appointments(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    # Ordered by the structured time (upcoming first); legacy rows without a
    # structured time (NULL) sort last in Postgres, then by most recent.
    result = await db.execute(
        select(Appointment)
        .where(Appointment.clinic_id == clinic_id)
        .order_by(Appointment.appointment_at.asc(), Appointment.created_at.desc())
    )
    return api_response(
        success=True,
        message="Appointments fetched successfully",
        data=serialize_models(result.scalars().all()),
    )


@router.post("/")
async def create_appointment(
    payload: AppointmentCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    # How this clinic books determines the flow: "token" (daily queue number,
    # no time slot) vs "time" (fixed slots with double-booking prevention).
    tenant = (await db.execute(select(Tenant).where(Tenant.id == clinic_id))).scalar_one_or_none()
    booking_mode = ((tenant.booking_mode if tenant else None) or "time").strip().lower()

    phone = (payload.phone or "").strip() or None

    # Same clinic lock the AI booking path takes. Both write to `appointments`, so
    # locking only one of them would still leave a race between a staff member
    # booking on the dashboard and the agent booking on a call at the same instant.
    # Transaction-scoped: released on commit, and safe behind the connection pooler.
    await repository.lock_clinic_for_booking(db, clinic_id)

    if booking_mode == "token":
        # Assign today's next sequential token. Under the lock above, so two
        # simultaneous bookings cannot read the same maximum and be handed the same
        # token number.
        today = repository.queue_today_str()
        token_num = await repository.next_token(clinic_id, today)
        display = payload.appointment_date or f"Token {token_num}"
        appointment = Appointment(
            clinic_id=clinic_id,
            patient_id=payload.patient_id or "manual",
            patient_name=payload.patient_name,
            appointment_date=display,
            appointment_at=None,
            duration_min=payload.duration_min or 30,
            token_number=token_num,
            token_date=today,
            phone=phone,
            reason=payload.reason,
            status=payload.status or "scheduled",
        )
        db.add(appointment)
        await db.commit()

        events.publish(clinic_id, {
            "id": f"appt-{appointment.id}",
            "type": "appointment",
            "name": appointment.patient_name,
            "meta": display,
            "ts": datetime.utcnow().isoformat(),
            "to": "/appointments",
        })

        if appointment.phone:
            asyncio.create_task(
                notifications.send_customer_confirmation(
                    clinic_id, appointment.phone, appointment.patient_name, display
                )
            )

        return api_response(
            success=True,
            message=f"Token {token_num} booked",
            data=serialize_model(appointment),
        )

    # ----- time mode (default) -----
    # Prevent double-booking: same clinic, overlapping scheduled slot. Checked in
    # THIS transaction, under the clinic lock, so the check and the insert cannot be
    # interleaved with another booking.
    if payload.appointment_at is not None:
        available = await repository.is_slot_free_in_session(
            db, clinic_id, payload.appointment_at, payload.duration_min
        )
        if not available:
            return api_response(
                success=False,
                message="That time slot is already booked. Please choose another time.",
                status_code=409,
            )

    # Derive a human display string when only the structured time was sent.
    display = payload.appointment_date
    if not display:
        display = payload.appointment_at.strftime("%d %b %Y, %I:%M %p") if payload.appointment_at else "Unspecified"

    appointment = Appointment(
        clinic_id=clinic_id,
        patient_id=payload.patient_id or "manual",
        patient_name=payload.patient_name,
        appointment_date=display,
        appointment_at=payload.appointment_at,
        duration_min=payload.duration_min or 30,
        phone=phone,
        reason=payload.reason,
        status=payload.status or "scheduled",
    )
    db.add(appointment)
    await db.commit()

    events.publish(clinic_id, {
        "id": f"appt-{appointment.id}",
        "type": "appointment",
        "name": appointment.patient_name,
        "meta": display,
        "ts": datetime.utcnow().isoformat(),
        "to": "/appointments",
    })

    # Best-effort WhatsApp confirmation to the customer (non-blocking).
    if appointment.phone:
        asyncio.create_task(
            notifications.send_customer_confirmation(
                clinic_id, appointment.phone, appointment.patient_name, display
            )
        )

    return api_response(
        success=True,
        message="Appointment created successfully",
        data=serialize_model(appointment),
    )


# ----- Token / queue endpoints (token mode) ---------------------------------

@router.get("/queue")
async def get_queue(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Today's queue: the "now serving" number, highest token issued, and the
    list of today's token appointments (ordered by token number)."""
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    today = repository.queue_today_str()
    status = await repository.get_queue_status(clinic_id, today)

    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.clinic_id == clinic_id,
            Appointment.token_date == today,
            Appointment.token_number.isnot(None),
        )
        .order_by(Appointment.token_number.asc())
    )
    return api_response(
        success=True,
        message="Queue fetched successfully",
        data={"status": status, "items": serialize_models(result.scalars().all())},
    )


@router.post("/queue/next")
async def queue_next(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advance the "now serving" number by one (auto-rolls over on a new day)."""
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    state = await repository.advance_queue(clinic_id)
    if state is None:
        return api_response(success=False, message="Clinic not found", status_code=404)
    return api_response(success=True, message="Now serving updated", data=state)


@router.post("/queue/set")
async def queue_set(
    payload: QueueSet,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the "now serving" number directly for today (also used to reset to 0)."""
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    state = await repository.set_queue(clinic_id, payload.number)
    if state is None:
        return api_response(success=False, message="Clinic not found", status_code=404)
    return api_response(success=True, message="Now serving updated", data=state)


@router.put("/{appointment_id}")
async def update_appointment(
    appointment_id: str,
    payload: AppointmentCreate,
    request: Request,
    current_user: dict = Depends(require_non_staff),
    db: AsyncSession = Depends(get_db),
):
    """Edit a booking. Doctor/manager only.

    `require_non_staff` here is not just about "editing": the payload carries
    `status`, so a staff member could send `status="cancelled"` and cancel a booking
    through this route. Guarding DELETE alone would have left that bypass wide open.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    aid = to_uuid(appointment_id)
    if aid is None:
        return api_response(success=False, message="Appointment not found", status_code=404)

    result = await db.execute(
        select(Appointment).where(Appointment.id == aid, Appointment.clinic_id == clinic_id)
    )
    appointment = result.scalar_one_or_none()
    if not appointment:
        return api_response(success=False, message="Appointment not found", status_code=404)

    changed = payload.dict(exclude_unset=True)
    for key, value in changed.items():
        setattr(appointment, key, value)
    await db.commit()

    await audit.record(
        audit.APPOINTMENT_UPDATED, actor=current_user, clinic_id=clinic_id,
        target_type="appointment", target_id=appointment.id,
        detail={"fields": sorted(changed.keys()), "status": appointment.status},
        request=request,
    )

    return api_response(
        success=True,
        message="Appointment updated successfully",
        data=serialize_model(appointment),
    )


@router.put("/{appointment_id}/reschedule")
async def reschedule_appointment(
    appointment_id: str,
    payload: AppointmentReschedule,
    request: Request,
    current_user: dict = Depends(require_non_staff),
    db: AsyncSession = Depends(get_db),
):
    """Move a booking to a new slot. Doctor/manager only.

    Restricted for the same reason as cancelling: moving a booking to an arbitrary
    date is functionally the same as cancelling it, so leaving this open to staff
    while blocking DELETE would make that block decorative. Staff can still *create*
    bookings — a walk-in at the front desk is the case that has to keep working.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    aid = to_uuid(appointment_id)
    if clinic_id is None or aid is None:
        return api_response(success=False, message="Appointment not found", status_code=404)

    appointment = (await db.execute(
        select(Appointment).where(Appointment.id == aid, Appointment.clinic_id == clinic_id)
    )).scalar_one_or_none()
    if not appointment:
        return api_response(success=False, message="Appointment not found", status_code=404)

    # Same no-double-book check, ignoring this appointment's own current slot.
    available = await repository.is_slot_available(
        clinic_id, payload.appointment_at, payload.duration_min, exclude_id=aid
    )
    if not available:
        return api_response(
            success=False,
            message="That time slot is already booked. Please choose another time.",
            status_code=409,
        )

    previous = appointment.appointment_date
    appointment.appointment_at = payload.appointment_at
    appointment.duration_min = payload.duration_min or 30
    appointment.appointment_date = payload.appointment_at.strftime("%d %b %Y, %I:%M %p")
    appointment.status = "scheduled"
    appointment.reminder_sent = False  # re-send a reminder for the new time
    await db.commit()

    await audit.record(
        audit.APPOINTMENT_UPDATED, actor=current_user, clinic_id=clinic_id,
        target_type="appointment", target_id=appointment.id,
        detail={
            "action": "rescheduled",
            "from": previous,
            "to": appointment.appointment_date,
            "patient_name": appointment.patient_name,
        },
        request=request,
    )

    return api_response(
        success=True,
        message="Appointment rescheduled",
        data=serialize_model(appointment),
    )


@router.delete("/{appointment_id}")
async def cancel_appointment(
    appointment_id: str,
    request: Request,
    current_user: dict = Depends(require_non_staff),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a booking. Doctor/manager only — staff must not be able to remove
    someone from the schedule. A soft cancel (status flips to "cancelled") rather
    than a row delete, so the slot history survives for reporting and disputes.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    aid = to_uuid(appointment_id)
    if aid is None:
        return api_response(success=False, message="Appointment not found", status_code=404)

    result = await db.execute(
        select(Appointment).where(Appointment.id == aid, Appointment.clinic_id == clinic_id)
    )
    appointment = result.scalar_one_or_none()
    if not appointment:
        return api_response(success=False, message="Appointment not found", status_code=404)

    appointment.status = "cancelled"
    await db.commit()

    await audit.record(
        audit.APPOINTMENT_CANCELLED, actor=current_user, clinic_id=clinic_id,
        target_type="appointment", target_id=appointment.id,
        detail={"patient_name": appointment.patient_name, "when": appointment.appointment_date},
        request=request,
    )

    return api_response(success=True, message="Appointment cancelled successfully")
