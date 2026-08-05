import asyncio
import logging
import re
import secrets
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Response, Depends, Request, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.vobiz.client import VobizClient
from backend.config.settings import settings
from backend.services.db import get_db
from backend.services import repository, notifications, events
from backend.services.call_tokens import mint_call_token, verify_call_token, token_ttl_minutes
from backend.routes.auth import get_current_user
from backend.models import CallLog, Tenant, Appointment
from backend.utils.helpers import api_response, serialize_models, to_uuid

logger = logging.getLogger("calls-router")
router = APIRouter(prefix="/calls", tags=["Calls"])


def _pick(params: dict, *keys):
    """Case-insensitive lookup across a set of possible parameter names."""
    lowered = {str(k).lower(): v for k, v in params.items()}
    for key in keys:
        val = lowered.get(key.lower())
        if val:
            return val
    return None


# A phone number is the ONLY thing these webhook fields may contain. This
# endpoint is public and its values used to be interpolated straight into the
# XML response, so anything else is dropped rather than escaped-and-forwarded.
_NUMBER_RE = re.compile(r"^\+?\d{4,20}$")


def _safe_number(value) -> str:
    """Return `value` only if it looks like a phone number, else "".

    Guards the public inbound webhook: `to`/`from` end up in the media-stream URL
    and (previously, unescaped) in the XML body. Allow-listing the shape stops
    XML/URL injection at the source instead of relying on output encoding alone.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if _NUMBER_RE.match(raw):
        return raw
    # Salvage a plausible number (providers sometimes send "sip:+91...@host").
    digits = "".join(ch for ch in raw if ch.isdigit())
    if 4 <= len(digits) <= 20:
        return ("+" + digits) if raw.lstrip().startswith("+") else digits
    logger.warning(f"Inbound webhook: discarded non-numeric value {raw[:40]!r}")
    return ""


@router.post("/twiml/inbound")
async def inbound_twiml(request: Request):
    """
    Webhook handler when Vobiz receives an inbound call.
    Resolves the destination DID and answers with Stream XML.

    Vobiz (Plivo-style) posts the call details as form fields, not query params,
    so we gather from query + form (+ JSON) and match common field-name variants.
    The full payload is logged so we can see exactly what the provider sends.
    """
    params = dict(request.query_params)
    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            body = await request.json()
            if isinstance(body, dict):
                params.update({k: str(v) for k, v in body.items()})
        else:
            form = await request.form()
            params.update({k: str(v) for k, v in form.items()})
    except Exception as e:
        logger.warning(f"Inbound webhook parse error: {e}")

    # VESTIGIAL PATH. Calls now arrive as Vobiz -> LiveKit SIP -> the LiveKit agent,
    # which carries the audio itself; the `/media-stream` websocket this XML points
    # at was removed on 2026-08-05 (see backend/websocket/handler.py for the proof
    # it was unused). The Vobiz trunk still lists this URL as its webhook, so the
    # endpoint stays reachable rather than 404-ing at the provider.
    #
    # This WARNING is deliberate: if the provider ever actually drives calls through
    # here we want to find out from the logs immediately, because the media route it
    # advertises no longer exists.
    logger.warning(
        "Legacy /twiml/inbound was called — the media-stream path it returns no "
        f"longer exists. Raw params: {params}"
    )

    to = _safe_number(_pick(params, "to", "To", "called", "CalledNumber", "destination", "did", "DID", "dnis", "dialed_number"))
    frm = _safe_number(_pick(params, "From", "from", "caller", "CallerNumber", "src", "source", "ani", "from_number"))
    logger.info(f"Vobiz Inbound resolved -> To: {to}, From: {frm}")

    ws_url = settings.SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
    ws_endpoint = (
        f"{ws_url}/media-stream"
        f"?destination={quote(to, safe='')}&phone={quote(frm, safe='')}"
    )
    xml_response = VobizClient.get_stream_xml(ws_endpoint)
    return Response(content=xml_response, media_type="application/xml")


@router.get("/logs")
async def get_call_logs(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Call history for the caller's clinic, newest first.

    Previously a hard `LIMIT 100` with no offset, so a busy clinic simply could not
    reach its older calls — an eleventh page did not exist. Now paginated, with a
    total so the dashboard can render page controls, plus status and phone/name
    filters. The composite index on (clinic_id, created_at DESC) serves the ordering.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    # Bounded so a single request cannot pull an entire history.
    capped = max(min(int(limit or 50), 200), 1)
    skip = max(int(offset or 0), 0)

    filters = [CallLog.clinic_id == clinic_id]
    if status:
        filters.append(CallLog.status == status.strip().lower())
    if search:
        term = f"%{search.strip()}%"
        filters.append(CallLog.phone.ilike(term) | CallLog.caller_name.ilike(term))

    total = (await db.execute(
        select(func.count()).select_from(CallLog).where(*filters)
    )).scalar() or 0

    rows = (await db.execute(
        select(CallLog)
        .where(*filters)
        .order_by(CallLog.created_at.desc())
        .limit(capped)
        .offset(skip)
    )).scalars().all()

    return api_response(
        success=True,
        message="Call logs retrieved successfully",
        # Still a bare list, so existing dashboard code keeps working; pagination
        # state rides alongside it.
        data=serialize_models(rows),
        meta={"total": int(total), "limit": capped, "offset": skip,
              "hasMore": skip + len(rows) < int(total)},
    )


# ----- Internal: authentication for the voice agent -------------------------
# Two layers on purpose:
#   1. ONE bootstrap endpoint (/agent-context) takes the long-lived shared secret
#      and resolves the tenant from the DIALED NUMBER alone.
#   2. Everything else takes a short-lived token bound to (clinic_id, call_id).
# Previously all nine endpoints shared one secret AND read `clinic_id` from the
# request body, so that single secret was a master key over every tenant's data.

def _agent_secret_ok(secret_header: str) -> bool:
    """Shared-secret check — used ONLY by the /agent-context bootstrap.

    The previous fallback to `settings.JWT_SECRET` is gone on purpose. It meant a
    deployment that forgot AGENT_INTERNAL_SECRET silently reused the session
    signing key as an API credential, so leaking it anywhere in the call path
    would let an attacker mint a token for any user on the platform.
    """
    secret = (settings.AGENT_INTERNAL_SECRET or "").strip()
    if not secret:
        logger.error(
            "AGENT_INTERNAL_SECRET is not set — agent endpoints are disabled. "
            "The voice agent cannot save bookings or call logs until it is set."
        )
        return False
    # Constant-time compare: a plain `==` leaks the secret one byte at a time to
    # an attacker who can measure response timing.
    return secrets.compare_digest(secret_header or "", secret)


async def require_call_scope(
    authorization: str = Header(default="", alias="Authorization"),
) -> dict:
    """Dependency for every agent endpoint except the bootstrap.

    The tenant comes from the token's claims, so a request body can no longer
    choose which clinic to read or write. A token is valid for exactly one call
    and expires by itself.
    """
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ").strip()
    claims = verify_call_token(token)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid per-call token is required. Call /api/calls/agent-context first.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


# ----- Internal: booking made by the LiveKit voice agent --------------------

class AgentBookRequest(BaseModel):
    # The clinic is taken from the call token, NOT from here — a request body must
    # never be able to choose which tenant a booking lands in.
    # Booking mode from the call context, so the endpoint can skip a tenant read.
    booking_mode: Optional[str] = None
    caller_phone: Optional[str] = None
    patient_name: str
    reason: Optional[str] = None
    # Healthcare intake collected on the call, saved to the patient record.
    age: Optional[int] = None
    gender: Optional[str] = None
    # Time mode: ISO-8601 datetime. Token mode ignores it.
    appointment_at: Optional[datetime] = None
    # Human display fallback (e.g. "kal shaam 5 baje") when no ISO time is parsed.
    appointment_date: Optional[str] = None
    duration_min: int = 30


def _did_variants(did: str):
    """Common phone-format variants so DID matching survives +/country-code
    differences between what Vobiz sends over SIP and what's stored in the DB."""
    d = (did or "").strip()
    if not d:
        return []
    digits = "".join(ch for ch in d if ch.isdigit())
    variants = [d]
    if digits:
        variants += [digits, "+" + digits]
        if len(digits) > 10:
            last10 = digits[-10:]
            variants += ["+91" + last10, "91" + last10, last10]
    seen, out = set(), []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


async def _resolve_tenant_from_did(did):
    """Resolve the tenant from the DIALED NUMBER only (never from client input).

    Tries the number's common format variants, then falls back to the sole tenant
    when the platform has exactly one (a dev convenience that cannot cross tenants
    — with two or more clinics `get_only_tenant()` returns None rather than guess).
    """
    if did:
        for cand in _did_variants(did):
            tenant = await repository.get_tenant_by_did(cand)
            if tenant:
                return tenant
    return await repository.get_only_tenant()


def _publish_appt_event(clinic_id, appt_id, name, display):
    """In-memory real-time dashboard notification (bell + lists). Fast, non-blocking."""
    try:
        events.publish(clinic_id, {
            "id": f"appt-{appt_id}",
            "type": "appointment",
            "name": name,
            "meta": display,
            "ts": datetime.utcnow().isoformat(),
            "to": "/appointments",
        })
    except Exception:
        pass


async def _post_book_side_effects(clinic_id, caller_phone, name, display, age=None, gender=None):
    """Non-critical work done AFTER the booking response: capture the caller as a
    contact (with any intake details) and send the WhatsApp confirmation. Kept off
    the critical path so the agent gets its token back fast."""
    if not caller_phone:
        return
    try:
        await repository.get_or_create_patient(clinic_id, caller_phone, name, age=age, gender=gender)
    except Exception as e:
        logger.warning(f"agent-book: contact upsert failed: {e}")
    try:
        await notifications.send_customer_confirmation(clinic_id, caller_phone, name, display)
    except Exception:
        pass


@router.post("/agent-book")
async def agent_book_appointment(
    payload: AgentBookRequest,
    claims: dict = Depends(require_call_scope),
    db: AsyncSession = Depends(get_db),
):
    """Persist a booking made by the LiveKit voice agent during a live call.

    Optimised for low latency: the critical path (assign the daily token / check
    the slot + insert the appointment) runs in ONE DB session; capturing the
    caller as a contact and sending the WhatsApp confirmation are deferred to a
    background task so the agent gets its token back fast.

    Auth is the per-call token, and the clinic comes from its claims — so a
    booking can only ever be written into the tenant the call was dispatched for.
    """
    clinic_id = to_uuid(claims["clinic_id"])
    if clinic_id is None:
        return api_response(success=False, message="Invalid clinic in call token.", status_code=400)

    # booking_mode is a hint from the call context purely to save a tenant read;
    # anything unexpected is re-read from the DB rather than trusted.
    booking_mode = (payload.booking_mode or "").strip().lower()
    if booking_mode not in ("time", "token"):
        booking_mode = ((await db.execute(
            select(Tenant.booking_mode).where(Tenant.id == clinic_id)
        )).scalar_one_or_none() or "time").strip().lower()

    caller_phone = (payload.caller_phone or "").strip() or None
    name = (payload.patient_name or "").strip() or "Caller"
    patient_ref = caller_phone or "agent"
    duration_min = int(payload.duration_min or 30)

    # Serialise bookings for THIS clinic until this transaction commits, so the
    # read-then-write below is atomic. Without it, two callers landing at the same
    # moment could be handed the same token number, or both given the same time slot.
    # Transaction-scoped, so it releases on commit and is safe behind the pooler.
    await repository.lock_clinic_for_booking(db, clinic_id)

    if booking_mode == "token":
        today = repository.queue_today_str()
        current_max = (await db.execute(
            select(func.max(Appointment.token_number)).where(
                Appointment.clinic_id == clinic_id,
                Appointment.token_date == today,
            )
        )).scalar()
        token_num = int(current_max or 0) + 1
        display = payload.appointment_date or f"Token {token_num}"
        appt = Appointment(
            clinic_id=clinic_id, patient_id=patient_ref, patient_name=name,
            appointment_date=display, appointment_at=None, duration_min=duration_min,
            token_number=token_num, token_date=today, phone=caller_phone,
            reason=payload.reason, status="scheduled",
        )
        db.add(appt)
        await db.commit()
        _publish_appt_event(clinic_id, appt.id, name, display)
        asyncio.create_task(_post_book_side_effects(clinic_id, caller_phone, name, display, age=payload.age, gender=payload.gender))
        return api_response(
            success=True, message=f"Token {token_num} booked",
            data={"booking_mode": "token", "token_number": token_num, "display": display},
        )

    # ----- time mode -----
    appt_at = payload.appointment_at
    # Checked inside THIS transaction (and under the clinic lock taken above), not in
    # a separate session — otherwise the gap between checking and inserting lets two
    # concurrent callers both take the same slot.
    if appt_at is not None and not await repository.is_slot_free_in_session(
        db, clinic_id, appt_at, duration_min
    ):
        return api_response(success=False, message="slot_unavailable", data={"available": False}, status_code=409)
    display = payload.appointment_date or (
        appt_at.strftime("%d %b %Y, %I:%M %p") if appt_at else "Unspecified"
    )
    appt = Appointment(
        clinic_id=clinic_id, patient_id=patient_ref, patient_name=name,
        appointment_date=display, appointment_at=appt_at, duration_min=duration_min,
        phone=caller_phone, reason=payload.reason, status="scheduled",
    )
    db.add(appt)
    await db.commit()
    _publish_appt_event(clinic_id, appt.id, name, display)
    asyncio.create_task(_post_book_side_effects(clinic_id, caller_phone, name, display))
    return api_response(
        success=True, message="Appointment booked",
        data={"booking_mode": "time", "display": display},
    )


# ----- Internal: additional agent actions (context / availability / queue /
#       caller lookup / register contact). All are scoped by the per-call token
#       issued by /agent-context. --------------------------------------------

class AgentContextRequest(BaseModel):
    # The DIALED number. This is the only thing that decides which tenant the
    # agent gets, and it comes from the SIP participant attributes, not from
    # anything a caller can set.
    did: Optional[str] = None
    # Unique id for this call (the LiveKit room name). The issued token is bound
    # to it, so it cannot be replayed against a different call.
    call_id: Optional[str] = None


class AgentAvailabilityRequest(BaseModel):
    appointment_at: datetime
    duration_min: int = 30


class AgentPhoneRequest(BaseModel):
    caller_phone: Optional[str] = None


class AgentPatientRequest(BaseModel):
    caller_phone: Optional[str] = None
    patient_name: str
    note: Optional[str] = None
    # Healthcare intake collected on the call, saved to the patient record.
    age: Optional[int] = None
    gender: Optional[str] = None


@router.post("/agent-context")
async def agent_context(
    payload: AgentContextRequest,
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
):
    """Bootstrap for one call: resolve the tenant and issue a scoped token.

    This is the ONLY endpoint that accepts the long-lived shared secret. It
    resolves the clinic from the dialed DID alone — it no longer honours a
    `clinic_id` supplied by the caller, which previously let anyone holding the
    secret read any tenant's prompt and knowledge base.

    The returned `call_token` is what every other agent endpoint requires, and it
    is bound to this clinic and this call.
    """
    if not _agent_secret_ok(x_internal_secret):
        return api_response(success=False, message="Unauthorized", status_code=401)

    tenant = await _resolve_tenant_from_did(payload.did)
    if tenant is None:
        logger.warning(f"agent-context: no clinic for DID {payload.did!r}")
        return api_response(success=False, message="Could not resolve a clinic.", status_code=404)

    clinic_id = tenant.get("id")
    # Without a call id there is nothing to bind the token to, so fall back to a
    # random one rather than issuing something broader in scope.
    call_id = (payload.call_id or "").strip() or f"call-{secrets.token_hex(8)}"
    call_token = mint_call_token(clinic_id, call_id)
    if call_token is None:
        return api_response(
            success=False,
            message="Agent credentials are not configured on the server.",
            status_code=503,
        )

    return api_response(success=True, message="ok", data={
        "clinic_id": clinic_id,
        "business_name": tenant.get("name") or "our business",
        "booking_mode": (tenant.get("booking_mode") or "time").strip().lower(),
        "system_prompt": tenant.get("system_prompt") or "",
        "knowledge_base": tenant.get("knowledge_base") or "",
        "voice": tenant.get("voice") or "",
        "language": tenant.get("language") or "",
        # Present this as `Authorization: Bearer <call_token>` on every other
        # /api/calls/agent-* request for the rest of this call.
        "call_token": call_token,
        "call_token_expires_in_min": token_ttl_minutes(),
        "call_id": call_id,
    })


@router.post("/agent-availability")
async def agent_availability(
    payload: AgentAvailabilityRequest,
    claims: dict = Depends(require_call_scope),
):
    """Is a specific time free? (time-slot clinics)."""
    available = await repository.is_slot_available(
        claims["clinic_id"], payload.appointment_at, payload.duration_min
    )
    return api_response(success=True, message="ok", data={"available": bool(available)})


@router.post("/agent-queue")
async def agent_queue(
    payload: AgentPhoneRequest,
    claims: dict = Depends(require_call_scope),
):
    """Live token/queue status (token clinics)."""
    today = repository.queue_today_str()
    caller_phone = (payload.caller_phone or "").strip() or None
    queue = await repository.get_queue_status(claims["clinic_id"], today, caller_phone)
    return api_response(success=True, message="ok", data=queue)


@router.post("/agent-lookup")
async def agent_lookup(
    payload: AgentPhoneRequest,
    claims: dict = Depends(require_call_scope),
):
    """Recognise the caller by phone: known?/name/history + nearest upcoming appt."""
    clinic_id = claims["clinic_id"]
    phone = (payload.caller_phone or "").strip() or None
    patient = await repository.lookup_patient_by_phone(phone, clinic_id) if phone else None
    upcoming = await repository.get_upcoming_appointment(clinic_id, phone) if phone else None
    return api_response(success=True, message="ok", data={
        "known": bool(patient),
        "name": (patient or {}).get("name"),
        "history": (patient or {}).get("history") or [],
        "upcoming": (
            {"when": upcoming.get("appointment_date"), "reason": upcoming.get("reason")}
            if upcoming else None
        ),
    })


# ----- Internal: call logging from the LiveKit voice agent -------------------
# The dashboard's Calls page, live-call view, recent-calls table, outcome chart,
# conversion funnel and monthly call quota all read `call_logs`. That table used to
# be written by the /media-stream websocket handler, but the current architecture is
# Vobiz -> LiveKit SIP -> LiveKit agent, which bypasses that websocket entirely — so
# nothing wrote call_logs and every one of those views sat empty. The agent now
# reports each call's lifecycle through these endpoints.


class AgentCallStartRequest(BaseModel):
    call_id: str
    caller_phone: Optional[str] = None
    direction: str = "inbound"


class AgentCallTranscriptRequest(BaseModel):
    call_id: str
    role: str  # "user" | "assistant"
    content: str


class AgentCallEndRequest(BaseModel):
    call_id: str
    status: str = "completed"


def _assert_own_call(claims: dict, call_id: str) -> None:
    """Reject a token being used against a call it was not issued for.

    Without this, any valid token could append transcript turns to — or close —
    an arbitrary `call_id`, including another tenant's live call (a plain IDOR).
    """
    if (call_id or "").strip() != claims.get("call_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This token is not valid for that call.",
        )


@router.post("/agent-call-start")
async def agent_call_start(
    payload: AgentCallStartRequest,
    claims: dict = Depends(require_call_scope),
):
    """Record that a call has started, so it shows up live on the dashboard."""
    _assert_own_call(claims, payload.call_id)
    await repository.upsert_call_start(
        payload.call_id,
        claims["clinic_id"],
        (payload.caller_phone or "").strip() or None,
        payload.direction or "inbound",
    )
    return api_response(success=True, message="Call logged")


@router.post("/agent-call-transcript")
async def agent_call_transcript(
    payload: AgentCallTranscriptRequest,
    claims: dict = Depends(require_call_scope),
):
    """Append one conversation turn to the call's transcript."""
    _assert_own_call(claims, payload.call_id)
    role = "assistant" if (payload.role or "").lower().startswith("a") else "user"
    text_content = (payload.content or "").strip()
    if not text_content:
        return api_response(success=True, message="Empty turn ignored")
    await repository.append_transcript(payload.call_id, role, text_content)
    return api_response(success=True, message="Turn appended")


@router.post("/agent-call-end")
async def agent_call_end(
    payload: AgentCallEndRequest,
    claims: dict = Depends(require_call_scope),
):
    """Close the call out: final status + duration (derived from created_at)."""
    _assert_own_call(claims, payload.call_id)
    call_status = (payload.status or "completed").strip().lower()
    if call_status not in ("completed", "failed", "no-answer"):
        call_status = "completed"
    await repository.set_call_status(payload.call_id, call_status)
    return api_response(success=True, message="Call closed")


@router.post("/agent-patient")
async def agent_patient(
    payload: AgentPatientRequest,
    claims: dict = Depends(require_call_scope),
):
    """Register the caller as a patient/contact (or update name), optional note."""
    phone = (payload.caller_phone or "").strip() or None
    patient = await repository.register_or_update_patient(
        claims["clinic_id"], phone, payload.patient_name, payload.note,
        age=payload.age, gender=payload.gender,
    )
    if patient is None:
        return api_response(success=False, message="Could not save the contact.", status_code=500)
    return api_response(success=True, message="Contact saved", data={
        "patient_id": patient.get("id"),
        "name": patient.get("name"),
    })
