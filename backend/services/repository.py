"""
Data-access helpers for non-request code paths (websocket handler, scheduler,
and the LLM tool functions). Each helper manages its own AsyncSession so callers
don't need FastAPI's request-scoped dependency.

All functions are safe to call before the DB is connected: they no-op (return
None/[] or do nothing) when the sessionmaker isn't available yet, mirroring the
previous `if db is not None` guards.
"""

import logging
from datetime import datetime

from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.services.db import get_sessionmaker
from backend.services import events
from backend.models import (
    Tenant, Patient, Appointment, CallLog, PhoneNumber, SipTrunk, WhatsAppMessage,
)
from backend.utils.helpers import serialize_model, to_uuid

logger = logging.getLogger("repository")


# ----- Tenant lookups -------------------------------------------------------

async def get_tenant_by_did(did: str):
    """Resolve a tenant from a dialed number, for calls arriving on the SHARED trunk.

    This is the legacy path: one Vobiz trunk carrying numbers Clarivo itself
    subscribed to. Numbers a customer brought from their own operator arrive on their
    own trunk instead and are resolved by `resolve_trunk_call`, which can additionally
    prove the number belongs to them.

    Two gates that were not here before:

      * `verification_status == "verified"`. A number nobody has proved must not
        answer real calls; otherwise the first account to type in a competitor's
        number would receive that competitor's calls. Numbers that predate
        verification were backfilled as verified by migration f766bbd4df0d, so this
        does not strand any existing tenant.
      * The legacy `tenants.did` fallback now only applies to tenants with NO rows in
        `phone_numbers`. That column has no status and no verification, so it was an
        ungated way into a tenant; restricting it to tenants that never migrated keeps
        it working for them without letting it override, or resurrect, a managed
        number that has been deactivated or removed.
    """
    Session = get_sessionmaker()
    if Session is None or not did:
        return None
    async with Session() as session:
        # Prefer the managed phone_numbers table (active, proven numbers).
        pn = (await session.execute(
            select(PhoneNumber).where(
                PhoneNumber.number == did,
                PhoneNumber.status == "active",
                PhoneNumber.verification_status == "verified",
            )
        )).scalar_one_or_none()
        if pn is not None:
            tenant = (await session.execute(
                select(Tenant).where(Tenant.id == pn.clinic_id)
            )).scalar_one_or_none()
            if tenant is not None:
                return serialize_model(tenant)

        # Fallback: the legacy single DID stored directly on the tenant, and only for
        # a tenant that has never used the managed table.
        tenant = (await session.execute(
            select(Tenant).where(Tenant.did == did)
        )).scalar_one_or_none()
        if tenant is None:
            return None
        managed = (await session.execute(
            select(func.count()).select_from(PhoneNumber).where(
                PhoneNumber.clinic_id == tenant.id
            )
        )).scalar() or 0
        if managed:
            logger.warning(
                "Ignoring legacy tenants.did match for clinic %s: it has %d managed "
                "phone number(s), so the dialed number %r is either deactivated or "
                "removed and must not be resolved through the legacy column.",
                tenant.id, managed, did,
            )
            return None
        return serialize_model(tenant)


async def resolve_trunk_call(trunk_id: str, did_variants: list):
    """Resolve a call that arrived on a tenant's OWN SIP trunk.

    This is where a customer-owned number is both authenticated and proven. The trunk
    identifies the tenant, because its digest credentials are generated per tenant and
    shown only in that tenant's dashboard. The dialed number then has to be one THAT
    tenant has claimed — the trunk says who is calling in, the number says who they are
    entitled to be answered as, and both must agree.

    Returns a dict with `outcome`:

      ok              - resolved; `tenant` is set, `verified_now` says whether this
                        call is what proved the number
      unknown_trunk   - no sip_trunks row for this LiveKit trunk id
      number_not_found- authenticated, but the dialed number is not claimed by them
      wrong_tenant    - the number belongs to a DIFFERENT clinic. The one outcome that
                        should be read as a possible attack rather than a mistake:
                        someone with tenant A's credentials is presenting tenant B's
                        number. `owner_clinic_id` is included so it can be audited.
      number_inactive - claimed by them, but they have switched it off

    Deliberately does NOT fall back to `get_only_tenant()`. On a single-tenant staging
    database that fallback would answer a misdirected or forged call as the only clinic
    present, which is exactly the confusion this function exists to prevent.
    """
    Session = get_sessionmaker()
    tid = (trunk_id or "").strip()
    if Session is None or not tid:
        return {"outcome": "unknown_trunk", "tenant": None, "verified_now": False}

    async with Session() as session:
        trunk = (await session.execute(
            select(SipTrunk).where(SipTrunk.livekit_trunk_id == tid)
        )).scalar_one_or_none()
        if trunk is None:
            return {"outcome": "unknown_trunk", "tenant": None, "verified_now": False}

        pn = None
        for cand in (did_variants or []):
            if not cand:
                continue
            pn = (await session.execute(
                select(PhoneNumber).where(PhoneNumber.number == cand)
            )).scalar_one_or_none()
            if pn is not None:
                break

        if pn is None:
            return {
                "outcome": "number_not_found", "tenant": None, "verified_now": False,
                "clinic_id": str(trunk.clinic_id),
            }

        if pn.clinic_id != trunk.clinic_id:
            return {
                "outcome": "wrong_tenant", "tenant": None, "verified_now": False,
                "clinic_id": str(trunk.clinic_id),
                "owner_clinic_id": str(pn.clinic_id),
                "number": pn.number,
            }

        if pn.status != "active":
            return {
                "outcome": "number_inactive", "tenant": None, "verified_now": False,
                "clinic_id": str(trunk.clinic_id), "number": pn.number,
            }

        # The proof. Reaching this line means a call authenticated with this tenant's
        # own credentials asked for a number this tenant has claimed, which is exactly
        # the thing an SMS OTP would have been standing in for.
        verified_now = False
        if pn.verification_status != "verified":
            pn.verification_status = "verified"
            pn.verified_at = datetime.utcnow()
            await session.commit()
            verified_now = True
            logger.info(
                "Verified %s for clinic %s via an authenticated call on trunk %s",
                pn.number, pn.clinic_id, tid,
            )

        tenant = (await session.execute(
            select(Tenant).where(Tenant.id == trunk.clinic_id)
        )).scalar_one_or_none()
        if tenant is None:
            # The trunk's FK is ON DELETE CASCADE, so this should be unreachable.
            return {"outcome": "unknown_trunk", "tenant": None, "verified_now": False}

        return {
            "outcome": "ok",
            "tenant": serialize_model(tenant),
            "verified_now": verified_now,
            "number": pn.number,
            "number_id": str(pn.id),
        }


async def find_number_state(did_variants: list):
    """Why a dialed number failed to resolve. Diagnostics only, never routing.

    "No clinic for DID +91…" is the same log line whether the number was never
    registered, is registered but unproven, or was switched off, and those need three
    different fixes. This distinguishes them without widening what is allowed to answer
    a call.
    """
    Session = get_sessionmaker()
    if Session is None:
        return {"exists": False}
    async with Session() as session:
        for cand in (did_variants or []):
            if not cand:
                continue
            pn = (await session.execute(
                select(PhoneNumber).where(PhoneNumber.number == cand)
            )).scalar_one_or_none()
            if pn is not None:
                return {
                    "exists": True,
                    "number": pn.number,
                    "status": pn.status,
                    "verification_status": pn.verification_status,
                    "source": pn.source,
                    "clinic_id": str(pn.clinic_id),
                }
    return {"exists": False}


async def get_tenant_by_id(clinic_id):
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return None
    async with Session() as session:
        result = await session.execute(select(Tenant).where(Tenant.id == cid))
        return serialize_model(result.scalar_one_or_none())


async def get_only_tenant():
    """Return the sole tenant when the DB has exactly one clinic, else None.

    Single-clinic fallback for the voice agent: if an inbound call can't be
    matched to a DID, and there's only one clinic, book against it. Returns None
    when there are zero or multiple clinics (ambiguous — don't guess).
    """
    Session = get_sessionmaker()
    if Session is None:
        return None
    async with Session() as session:
        rows = (await session.execute(select(Tenant).limit(2))).scalars().all()
        if len(rows) == 1:
            return serialize_model(rows[0])
    return None


async def log_whatsapp_message(clinic_id, to_phone, kind, template, body, status="sent", error=None):
    """Record a WhatsApp message send (best-effort; never raises)."""
    try:
        Session = get_sessionmaker()
        cid = to_uuid(clinic_id)
        if Session is None or cid is None:
            return
        async with Session() as session:
            session.add(WhatsAppMessage(
                clinic_id=cid,
                to_phone=to_phone,
                kind=kind,
                template=template,
                body=body,
                status=status,
                error=error,
            ))
            await session.commit()
    except Exception as e:
        logger.warning(f"log_whatsapp_message failed: {e}")


async def is_over_monthly_quota(clinic_id, limit) -> bool:
    """True if the tenant has reached/exceeded `limit` calls this billing month.

    Fail-open: returns False when unconfigured, when there's no positive limit, or on
    any error, so a problem with the CHECK never blocks a legitimate call. Rejecting
    a paying customer's caller because a count failed is worse than allowing one call
    over the limit.

    The month boundary comes from services/billing_period, which anchors to the
    billing timezone. Anchoring to UTC (as this did) meant that during the first
    5h30m of a month, calls made that morning in India were counted against the
    PREVIOUS month's quota — so a customer could be refused a call they were
    entitled to.
    """
    if not limit or limit <= 0:
        return False
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return False
    from backend.services import billing_period
    month_start = billing_period.month_start_utc()
    async with Session() as session:
        used = (await session.execute(
            select(func.count()).select_from(CallLog).where(
                CallLog.clinic_id == cid, CallLog.created_at >= month_start
            )
        )).scalar() or 0
    return used >= int(limit)


# ----- Patient / appointment helpers (used by LLM tools) --------------------

async def lookup_patient_by_phone(phone: str, clinic_id=None):
    Session = get_sessionmaker()
    if Session is None or not phone:
        return None
    async with Session() as session:
        stmt = select(Patient).where(Patient.phone == phone)
        cid = to_uuid(clinic_id) if clinic_id else None
        if cid is not None:
            stmt = stmt.where(Patient.clinic_id == cid)
        result = await session.execute(stmt)
        return serialize_model(result.scalars().first())


async def get_or_create_patient(clinic_id, phone, name=None, age=None, gender=None):
    """Find a patient by (clinic_id, phone), or create a new lead if missing.

    Used during inbound calls so an unknown caller who books is captured as a
    contact. If we learn a real name (or age/gender) for an existing record, fill
    in whatever is still missing. Returns the serialized patient dict (with id),
    or None if unconfigured.
    """
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None or not phone:
        return None
    clean_name = (name or "").strip()
    clean_age = age if (isinstance(age, int) and age > 0) else None
    clean_gender = (gender or "").strip() or None
    async with Session() as session:
        result = await session.execute(
            select(Patient).where(Patient.clinic_id == cid, Patient.phone == phone)
        )
        patient = result.scalar_one_or_none()

        if patient is None:
            patient = Patient(
                clinic_id=cid,
                name=clean_name or "Caller",
                phone=phone,
                age=clean_age,
                gender=clean_gender,
                history=[],
                source="agent",
            )
            session.add(patient)
            try:
                await session.commit()
            except IntegrityError:
                # Created concurrently (unique clinic_id+phone) -> fetch the winner.
                await session.rollback()
                result = await session.execute(
                    select(Patient).where(Patient.clinic_id == cid, Patient.phone == phone)
                )
                patient = result.scalar_one_or_none()
        else:
            changed = False
            if clean_name and (not patient.name or patient.name == "Caller"):
                patient.name = clean_name
                changed = True
            if clean_age is not None and not patient.age:
                patient.age = clean_age
                changed = True
            if clean_gender and not patient.gender:
                patient.gender = clean_gender
                changed = True
            if changed:
                await session.commit()

        return serialize_model(patient)


async def register_or_update_patient(clinic_id, phone=None, name=None, note=None, age=None, gender=None):
    """Create a patient/contact (or update an existing one by phone), optionally
    appending a note to their history and filling in age/gender.

    Used by the voice agent's register_patient tool so every caller can be
    captured in the dashboard's Contacts even without booking. Works with no phone
    (blocked caller ID) by creating a name-only lead. Idempotent by (clinic, phone).
    """
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return None
    clean_name = (name or "").strip()
    clean_phone = (phone or "").strip() or None
    clean_age = age if (isinstance(age, int) and age > 0) else None
    clean_gender = (gender or "").strip() or None
    async with Session() as session:
        patient = None
        if clean_phone:
            patient = (await session.execute(
                select(Patient).where(Patient.clinic_id == cid, Patient.phone == clean_phone)
            )).scalar_one_or_none()

        if patient is None:
            patient = Patient(
                clinic_id=cid,
                name=clean_name or "Caller",
                phone=clean_phone,
                age=clean_age,
                gender=clean_gender,
                history=[note] if note else [],
                source="agent",
            )
            session.add(patient)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if clean_phone:
                    patient = (await session.execute(
                        select(Patient).where(Patient.clinic_id == cid, Patient.phone == clean_phone)
                    )).scalar_one_or_none()
        else:
            changed = False
            if clean_name and (not patient.name or patient.name == "Caller"):
                patient.name = clean_name
                changed = True
            if clean_age is not None and not patient.age:
                patient.age = clean_age
                changed = True
            if clean_gender and not patient.gender:
                patient.gender = clean_gender
                changed = True
            if note:
                patient.history = (patient.history or []) + [note]
                changed = True
            if changed:
                await session.commit()

        return serialize_model(patient)


async def get_upcoming_appointment(clinic_id, phone):
    """The caller's nearest future scheduled appointment (time mode), or None."""
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None or not phone:
        return None
    async with Session() as session:
        appt = (await session.execute(
            select(Appointment).where(
                Appointment.clinic_id == cid,
                Appointment.phone == phone,
                Appointment.status == "scheduled",
                Appointment.appointment_at.isnot(None),
                Appointment.appointment_at >= datetime.now(),
            ).order_by(Appointment.appointment_at.asc())
        )).scalars().first()
        return serialize_model(appt) if appt else None


async def create_appointment_record(
    clinic_id, patient_id, patient_name, appointment_date, reason,
    status="scheduled", appointment_at=None, duration_min=30, phone=None,
    token_number=None, token_date=None,
) -> bool:
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return False
    async with Session() as session:
        appt = Appointment(
            clinic_id=cid,
            patient_id=str(patient_id) if patient_id is not None else None,
            patient_name=patient_name,
            appointment_date=appointment_date,
            appointment_at=appointment_at,
            duration_min=int(duration_min or 30),
            token_number=token_number,
            token_date=token_date,
            phone=phone,
            reason=reason,
            status=status,
        )
        session.add(appt)
        await session.commit()
        # Real-time notification (best-effort; never blocks the booking).
        try:
            events.publish(cid, {
                "id": f"appt-{appt.id}",
                "type": "appointment",
                "name": patient_name,
                "meta": appointment_date,
                "ts": datetime.utcnow().isoformat(),
                "to": "/appointments",
            })
        except Exception:
            pass
        return True


async def lock_clinic_for_booking(session, clinic_id) -> None:
    """Serialise bookings for one clinic for the rest of this TRANSACTION.

    Booking had two read-then-write races, both of which produce a wrong answer a
    customer would notice:

      * **time mode** — `is_slot_available` ran in its own session, then the insert
        happened separately. Two callers asking for 15:00 at the same moment both
        passed the check and both got the slot.
      * **token mode** — `SELECT max(token_number)` then insert `max + 1`. Two
        concurrent callers read the same maximum and were both handed the SAME token
        number, so two people arrive believing they are number 5.

    `pg_advisory_xact_lock` is TRANSACTION-scoped: it is released automatically at
    COMMIT or ROLLBACK. That distinction matters here, because this database is
    behind Supabase's pooler — a *session*-scoped advisory lock leaks onto a pooled
    backend and never releases (measured; it is why background-job election uses a
    lease table instead). A transaction-scoped lock is safe because the whole
    transaction is pinned to one backend for its duration.

    Scoped per clinic, so one busy tenant never blocks another.
    """
    if clinic_id is None:
        return
    # hashtext gives a stable bigint from the clinic id; the constant namespaces it
    # so it cannot collide with any other advisory lock in the system.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, hashtext(:cid))"),
        {"ns": 4242, "cid": str(clinic_id)},
    )


async def is_slot_free_in_session(session, clinic_id, start_dt, duration_min=30, exclude_id=None) -> bool:
    """Overlap check that runs in the CALLER'S transaction.

    `is_slot_available` opens its own session, which is why it cannot be combined
    with an insert atomically. Use this together with `lock_clinic_for_booking` so
    the check and the insert are one indivisible step.
    """
    cid = to_uuid(clinic_id)
    if cid is None or start_dt is None:
        return True
    from datetime import timedelta
    dur = int(duration_min or 30)
    req_end = start_dt + timedelta(minutes=dur)
    rows = (await session.execute(
        select(Appointment).where(
            Appointment.clinic_id == cid,
            Appointment.status == "scheduled",
            Appointment.appointment_at.isnot(None),
            Appointment.appointment_at >= start_dt - timedelta(hours=6),
            Appointment.appointment_at <= req_end + timedelta(hours=6),
        )
    )).scalars().all()
    for existing in rows:
        if exclude_id is not None and str(existing.id) == str(exclude_id):
            continue
        e_start = existing.appointment_at
        e_end = e_start + timedelta(minutes=int(existing.duration_min or 30))
        if e_start < req_end and e_end > start_dt:
            return False
    return True


async def is_slot_available(clinic_id, start_dt, duration_min=30, exclude_id=None) -> bool:
    """True if no scheduled appointment overlaps [start_dt, start_dt + duration).

    Single-capacity per clinic for now. Fail-open: returns True when the DB isn't
    configured or start_dt is None, so a check problem never blocks a booking.
    """
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None or start_dt is None:
        return True
    from datetime import timedelta
    dur = int(duration_min or 30)
    req_start = start_dt
    req_end = start_dt + timedelta(minutes=dur)
    # Only fetch appointments whose start is near the request (bounds the scan).
    window_lo = req_start - timedelta(hours=6)
    window_hi = req_end + timedelta(hours=6)
    async with Session() as session:
        rows = (await session.execute(
            select(Appointment).where(
                Appointment.clinic_id == cid,
                Appointment.status == "scheduled",
                Appointment.appointment_at.isnot(None),
                Appointment.appointment_at >= window_lo,
                Appointment.appointment_at <= window_hi,
            )
        )).scalars().all()
    for a in rows:
        if exclude_id is not None and str(a.id) == str(exclude_id):
            continue
        a_start = a.appointment_at
        a_end = a_start + timedelta(minutes=int(a.duration_min or 30))
        if a_start < req_end and a_end > req_start:  # overlap
            return False
    return True


# ----- Token / queue mode helpers -------------------------------------------

def queue_today_str() -> str:
    """Local wall-clock date (YYYY-MM-DD) used for daily token numbering.

    Matches the naive-local convention used elsewhere (appointment_at, etc.).
    """
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


async def next_token(clinic_id, date_str) -> int:
    """Next daily token number for a clinic: highest issued that day + 1 (min 1)."""
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return 1
    async with Session() as session:
        current_max = (await session.execute(
            select(func.max(Appointment.token_number)).where(
                Appointment.clinic_id == cid,
                Appointment.token_date == date_str,
            )
        )).scalar()
    return int(current_max or 0) + 1


async def get_queue_status(clinic_id, date_str, caller_phone=None) -> dict:
    """Today's queue state: the "now serving" number, the highest token issued,
    and (when caller_phone is given) the caller's own token + how many are ahead.
    """
    status = {
        "date": date_str,
        "current_number": 0,
        "total_issued": 0,
        "caller_token": None,
        "ahead": None,
    }
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return status
    async with Session() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.id == cid)
        )).scalar_one_or_none()
        # The "now serving" counter is only valid for its own day.
        if tenant is not None and tenant.queue_current_date == date_str:
            status["current_number"] = int(tenant.queue_current_number or 0)

        total = (await session.execute(
            select(func.max(Appointment.token_number)).where(
                Appointment.clinic_id == cid,
                Appointment.token_date == date_str,
            )
        )).scalar()
        status["total_issued"] = int(total or 0)

        if caller_phone:
            rows = (await session.execute(
                select(Appointment.token_number).where(
                    Appointment.clinic_id == cid,
                    Appointment.token_date == date_str,
                    Appointment.phone == caller_phone,
                    Appointment.token_number.isnot(None),
                )
            )).scalars().all()
            tokens = sorted(int(t) for t in rows if t is not None)
            if tokens:
                cur = status["current_number"]
                # Prefer their next upcoming token; else their latest one.
                upcoming = [t for t in tokens if t >= cur]
                caller_token = upcoming[0] if upcoming else tokens[-1]
                status["caller_token"] = caller_token
                status["ahead"] = max(caller_token - cur, 0)
    return status


async def advance_queue(clinic_id) -> dict:
    """Advance the "now serving" number by one (staff "Next" button).

    Rolls over automatically on a new day: the first advance of the day sets the
    counter to 1 and stamps today's date. Returns the new state, or None.
    """
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return None
    today = queue_today_str()
    async with Session() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.id == cid)
        )).scalar_one_or_none()
        if tenant is None:
            return None
        if tenant.queue_current_date != today:
            tenant.queue_current_date = today
            tenant.queue_current_number = 1
        else:
            tenant.queue_current_number = int(tenant.queue_current_number or 0) + 1
        await session.commit()
        return {"current_number": int(tenant.queue_current_number), "date": today}


async def set_queue(clinic_id, number) -> dict:
    """Set the "now serving" number directly for today (manual set / reset to 0)."""
    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return None
    today = queue_today_str()
    n = max(int(number or 0), 0)
    async with Session() as session:
        tenant = (await session.execute(
            select(Tenant).where(Tenant.id == cid)
        )).scalar_one_or_none()
        if tenant is None:
            return None
        tenant.queue_current_number = n
        tenant.queue_current_date = today
        await session.commit()
        return {"current_number": n, "date": today}


async def get_patient_by_id(patient_id):
    Session = get_sessionmaker()
    pid = to_uuid(patient_id)
    if Session is None or pid is None:
        return None
    async with Session() as session:
        result = await session.execute(select(Patient).where(Patient.id == pid))
        return serialize_model(result.scalar_one_or_none())


# ----- Call log helpers (used by the websocket handler) ---------------------

async def upsert_call_start(call_id: str, clinic_id, caller_phone: str, direction: str):
    """Create or update the call_logs row when a media stream starts."""
    Session = get_sessionmaker()
    if Session is None or not call_id:
        return
    cid = to_uuid(clinic_id) if clinic_id else None
    async with Session() as session:
        values = {
            "call_id": call_id,
            "status": "active",
            "clinic_id": cid,
            "caller_name": caller_phone,
            "phone": caller_phone,
            "direction": direction,
        }
        stmt = pg_insert(CallLog).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["call_id"],
            set_={
                "status": "active",
                "clinic_id": cid,
                "caller_name": caller_phone,
                "phone": caller_phone,
                "direction": direction,
            },
        )
        await session.execute(stmt)
        await session.commit()
    # Real-time notification for an incoming call (best-effort).
    try:
        events.publish(cid, {
            "id": f"call-{call_id}",
            "type": "call",
            "name": caller_phone or "unknown",
            "meta": direction or "inbound",
            "ts": datetime.utcnow().isoformat(),
            "to": "/calls",
        })
    except Exception:
        pass


async def append_transcript(call_id: str, role: str, content: str):
    """Append one {role, content} message to a call's JSONB transcript."""
    Session = get_sessionmaker()
    if Session is None or not call_id:
        return
    from datetime import datetime as _dt
    async with Session() as session:
        result = await session.execute(select(CallLog).where(CallLog.call_id == call_id))
        call_log = result.scalar_one_or_none()
        message = {"role": role, "content": content}
        now = _dt.utcnow()
        if call_log is None:
            session.add(CallLog(call_id=call_id, transcript=[message], last_activity_at=now))
        else:
            # Reassign (not in-place append) so SQLAlchemy detects the change.
            call_log.transcript = (call_log.transcript or []) + [message]
            # Marks how far the conversation actually got, so a call whose "ended"
            # report never arrives can still be closed with a real duration.
            call_log.last_activity_at = now
        await session.commit()


async def set_call_status(call_id: str, status: str):
    Session = get_sessionmaker()
    if Session is None or not call_id:
        return
    from datetime import datetime as _dt
    async with Session() as session:
        result = await session.execute(select(CallLog).where(CallLog.call_id == call_id))
        call_log = result.scalar_one_or_none()
        if call_log is not None:
            call_log.status = status
            if status in ("completed", "failed", "transferred") and call_log.created_at:
                delta = _dt.utcnow() - call_log.created_at
                call_log.duration = max(int(delta.total_seconds()), 0)
                call_log.last_activity_at = _dt.utcnow()
            await session.commit()


async def close_stale_calls(max_age_minutes: int = 15) -> int:
    """Close call_logs rows left stuck at status="active"; returns how many.

    The agent reports "call ended" on a best-effort background task. On Windows,
    LiveKit's native layer panics during call teardown
    (`malformed serialized RtcError` in webrtc-sys/src/rtc_error.rs) and kills the
    worker before that report goes out — observed on a real call, which stayed
    `active` with `duration: 0` permanently. Left alone those rows accumulate, the
    dashboard's live view shows calls that will never end, and average-duration
    stats are dragged toward zero.

    Duration comes from the last transcript turn (`last_activity_at`) rather than
    "now", so a row swept ten minutes late does not report a ten-minute call. A row
    that never got a single turn is marked `failed` — nothing was ever said.
    """
    Session = get_sessionmaker()
    if Session is None:
        return 0
    from datetime import datetime as _dt, timedelta as _td
    cutoff = _dt.utcnow() - _td(minutes=max(int(max_age_minutes), 1))
    closed = 0
    async with Session() as session:
        rows = (await session.execute(
            select(CallLog).where(
                CallLog.status == "active",
                CallLog.created_at < cutoff,
            )
        )).scalars().all()
        for row in rows:
            turns = len(row.transcript or []) if isinstance(row.transcript, list) else 0
            end_at = row.last_activity_at or row.created_at
            if turns > 0:
                # The caller did have a conversation; the agent just died before
                # it could say so.
                row.status = "completed"
                row.duration = max(int((end_at - row.created_at).total_seconds()), 0)
            else:
                row.status = "failed"
                row.duration = 0
            row.last_activity_at = end_at
            closed += 1
        if closed:
            await session.commit()
    if closed:
        logger.warning(
            f"Closed {closed} stale 'active' call(s) older than {max_age_minutes}m. "
            "The agent's end-of-call report did not arrive — usually the LiveKit "
            "teardown panic on Windows. Running the agent on Linux removes the cause."
        )
    return closed


# ----- Scheduler helpers ----------------------------------------------------

async def get_due_appointments(now_iso: str, limit_iso: str):
    Session = get_sessionmaker()
    if Session is None:
        return []
    async with Session() as session:
        stmt = select(Appointment).where(
            Appointment.status == "scheduled",
            Appointment.appointment_date >= now_iso,
            Appointment.appointment_date <= limit_iso,
        )
        result = await session.execute(stmt)
        return [serialize_model(row) for row in result.scalars().all()]


async def mark_appointment_status(appointment_id, status: str):
    Session = get_sessionmaker()
    aid = to_uuid(appointment_id)
    if Session is None or aid is None:
        return
    async with Session() as session:
        result = await session.execute(select(Appointment).where(Appointment.id == aid))
        appt = result.scalar_one_or_none()
        if appt is not None:
            appt.status = status
            await session.commit()
