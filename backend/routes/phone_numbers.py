"""Phone numbers a tenant's assistant answers.

The model here is **the customer owns the number**. They keep it with their own
telephony operator, and forward it into the SIP trunk we create for them alone
(services/livekit_sip.py). They sign their own CAF/KYC; Clarivo is the software layer.

That is a change of direction. `POST /provision` used to claim a DID out of Clarivo's
own Vobiz inventory and hand it over, which made us the subscriber of record for a line
another business answers. It is now gated behind `settings.ALLOW_PLATFORM_NUMBERS`,
which defaults to off — see docs/PLAN-number-ownership.md.

Two consequences run through every handler below:

  * A number is not routable until it is **proven**. `verification_status` starts at
    'pending' and is flipped by the first inbound call that authenticates as this
    tenant (routes/calls.py). Until then the row exists, appears in the dashboard, and
    is on the trunk so the test call can arrive — but it will not serve real traffic.
  * The trunk is **derived state**. Its number list is rebuilt from this table on every
    change, rather than patched, so a failed sync can never leave LiveKit holding a
    number the tenant has removed.
"""

import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.services import plans, audit, livekit_sip
from backend.services.limiter import limiter
from backend.routes.auth import get_current_user
from backend.models import PhoneNumber, SipTrunk, Tenant
from backend.config.settings import settings
from backend.integrations.vobiz.client import VobizNumbersAPI
from backend.utils.helpers import api_response, serialize_model, serialize_models, to_uuid

logger = logging.getLogger("phone-numbers-router")
router = APIRouter(prefix="/phone-numbers", tags=["Phone Numbers"])

MANAGER_ROLES = {"doctor", "admin"}
# Lenient E.164-style check: optional +, leading non-zero digit, 7-16 digits total.
PHONE_RE = re.compile(r"^\+?[1-9]\d{6,15}$")

SOURCE_BYO = "bring_your_own"
SOURCE_PLATFORM = "platform_provisioned"
VERIFY_PENDING = "pending"
VERIFY_VERIFIED = "verified"


def _digits(value: str) -> str:
    """Digits only, so "+918065480571" and "918065480571" compare equal."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


async def _claimed_numbers(db: AsyncSession) -> set:
    """Digit-only forms of every number already claimed by ANY clinic."""
    rows = (await db.execute(select(PhoneNumber.number))).scalars().all()
    return {_digits(n) for n in rows if n}


def _is_assignable(item: dict) -> bool:
    """A Vobiz inventory number usable for inbound voice."""
    if not item.get("e164"):
        return False
    if item.get("is_blocked"):
        return False
    if (item.get("status") or "").lower() not in ("active", ""):
        return False
    caps = item.get("capabilities") or {}
    # voice_enabled is the account-level flag; capabilities.voice is the carrier's.
    return bool(item.get("voice_enabled", True)) and bool(caps.get("voice", True))


def _require_manager(current_user: dict):
    if current_user.get("role") not in MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only clinic admins can manage phone numbers",
        )


async def _tenant_row(db: AsyncSession, clinic_id) -> tuple:
    """(name, subscription, number_limit) for a clinic, in one read."""
    row = (await db.execute(
        select(Tenant.name, Tenant.subscription, Tenant.number_limit).where(Tenant.id == clinic_id)
    )).first()
    if row is None:
        return ("", plans.DEFAULT_PLAN_KEY, None)
    return (row[0] or "", row[1] or plans.DEFAULT_PLAN_KEY, row[2])


async def _tenant_plan(db: AsyncSession, clinic_id) -> tuple:
    """(plan_key, plan_name, number_limit_override) for a clinic."""
    _name, key, override = await _tenant_row(db, clinic_id)
    return key, plans.get_plan(key)["name"], override


async def _number_quota(db: AsyncSession, clinic_id) -> tuple:
    """(is_allowed_another, currently_used, limit) for this clinic's numbers.

    Applied to BOTH doors now. It used to guard only `/provision`, so a tenant could
    walk past their plan by connecting numbers instead of claiming them — while those
    connected numbers still counted against the cap, which made the limit read as
    arbitrary rather than generous.
    """
    key, _name, override = await _tenant_plan(db, clinic_id)
    limit = plans.included_numbers(key, override)
    used = (await db.execute(
        select(func.count()).select_from(PhoneNumber).where(PhoneNumber.clinic_id == clinic_id)
    )).scalar() or 0
    return (used < limit), int(used), int(limit)


# ----- per-tenant SIP trunk -------------------------------------------------

async def _trunk_row(db: AsyncSession, clinic_id) -> Optional[SipTrunk]:
    return (await db.execute(
        select(SipTrunk).where(SipTrunk.clinic_id == clinic_id)
    )).scalar_one_or_none()


async def _ensure_trunk_row(db: AsyncSession, clinic_id) -> Optional[SipTrunk]:
    """The clinic's trunk row, creating it (with fresh credentials) if absent.

    Committed on its own rather than as part of the caller's transaction: the trunk and
    the phone number are separate facts, and a LiveKit failure must not roll back a
    number the customer successfully added.
    """
    trunk = await _trunk_row(db, clinic_id)
    if trunk is not None:
        return trunk
    username, password = livekit_sip.generate_credentials()
    trunk = SipTrunk(
        clinic_id=clinic_id,
        auth_username=username,
        auth_password=password,
        sip_host=livekit_sip.sip_host() or None,
        status="pending",
    )
    db.add(trunk)
    try:
        await db.commit()
    except IntegrityError:
        # Two requests raced to create the clinic's trunk. The UNIQUE index on
        # clinic_id is what makes this safe to lose: re-read and use the winner,
        # because issuing a second set of credentials would silently invalidate the
        # ones the customer may already be configuring.
        await db.rollback()
        trunk = await _trunk_row(db, clinic_id)
    return trunk


async def _trunk_number_list(db: AsyncSession, clinic_id) -> list:
    """Numbers that belong on the trunk.

    Includes numbers still awaiting verification — that is the point, the proving call
    has to be able to arrive. Excludes ones the customer has deactivated, so pausing a
    line stops calls at LiveKit rather than relying on a check further in.
    """
    rows = (await db.execute(
        select(PhoneNumber.number).where(
            PhoneNumber.clinic_id == clinic_id,
            PhoneNumber.status == "active",
        )
    )).scalars().all()
    return [n for n in rows if n]


async def _sync_trunk(db: AsyncSession, clinic_id, clinic_name: str) -> dict:
    """Push this clinic's number list to LiveKit, creating the trunk if needed.

    Never raises. Returns the livekit_sip result dict so a caller can surface a
    message; the trunk row records the outcome either way, which is what the dashboard
    reads to explain a pending connection.
    """
    trunk = await _ensure_trunk_row(db, clinic_id)
    if trunk is None:
        return {"ok": False, "error": "Could not prepare the phone connection."}

    numbers = await _trunk_number_list(db, clinic_id)

    if not livekit_sip.enabled():
        trunk.status = "pending"
        trunk.last_error = (
            "The server is not configured to create phone connections yet "
            "(LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET)."
        )
        trunk.updated_at = datetime.utcnow()
        await db.commit()
        return {"ok": False, "error": trunk.last_error}

    if not numbers:
        # Nothing active left. The trunk cannot simply be emptied: LiveKit reads an empty
        # numbers list as "accept ANY dialed number", so an emptied trunk would start
        # catching other tenants' calls. So the LiveKit objects go, and this row stays.
        #
        # Keeping the row is the point. It holds the username and password the customer
        # already configured at their operator, so when they switch a number back on the
        # trunk is rebuilt with the SAME credentials and their operator config keeps
        # working. Only the LiveKit trunk id changes, and the customer never sees that.
        if trunk.livekit_trunk_id or trunk.livekit_dispatch_rule_id:
            await livekit_sip.delete_trunk(
                trunk_id=trunk.livekit_trunk_id or "",
                dispatch_rule_id=trunk.livekit_dispatch_rule_id or "",
            )
            logger.info(
                f"Clinic {clinic_id} has no active numbers; released SIP trunk "
                f"{trunk.livekit_trunk_id} and kept its credentials."
            )
        trunk.livekit_trunk_id = None
        trunk.livekit_dispatch_rule_id = None
        trunk.status = "pending"
        trunk.last_error = None
        trunk.synced_at = None
        trunk.updated_at = datetime.utcnow()
        await db.commit()
        return {"ok": True, "error": ""}

    if trunk.livekit_trunk_id:
        result = await livekit_sip.replace_trunk(
            trunk_id=trunk.livekit_trunk_id,
            clinic_id=clinic_id,
            clinic_name=clinic_name,
            numbers=numbers,
            auth_username=trunk.auth_username,
            auth_password=trunk.auth_password,
            allowed_addresses=trunk.allowed_addresses,
        )
    else:
        result = await livekit_sip.create_trunk(
            clinic_id=clinic_id,
            clinic_name=clinic_name,
            numbers=numbers,
            auth_username=trunk.auth_username,
            auth_password=trunk.auth_password,
            allowed_addresses=trunk.allowed_addresses,
        )
        if result.get("ok"):
            trunk.livekit_trunk_id = result.get("trunk_id") or None
            trunk.livekit_dispatch_rule_id = result.get("dispatch_rule_id") or None

    if result.get("ok"):
        trunk.status = "active"
        trunk.last_error = None
        trunk.synced_at = datetime.utcnow()
        # Record the host alongside the ids: if LIVEKIT_SIP_HOST is later changed we
        # still know what this customer was told to configure.
        trunk.sip_host = livekit_sip.sip_host() or trunk.sip_host
    else:
        if not trunk.livekit_trunk_id:
            trunk.status = "pending"
        trunk.last_error = result.get("error") or "Unknown error"
    trunk.updated_at = datetime.utcnow()
    await db.commit()
    return result


def _trunk_payload(trunk: Optional[SipTrunk], numbers: list) -> dict:
    """The connection details a customer hands to their operator.

    The password is returned in full, unlike `tenants.whatsapp_access_token` which is
    masked. The difference is who authored it: we generate this one, so masking it
    would leave the customer with no way to obtain the credential they are required to
    configure. It is manager-only and rate limited instead, and `rotate` exists for
    when it has been shared too widely.
    """
    if trunk is None:
        return {"configured": False}
    return {
        "configured": True,
        "status": trunk.status,
        "sip_host": trunk.sip_host or livekit_sip.sip_host() or "",
        "auth_username": trunk.auth_username,
        "auth_password": trunk.auth_password,
        "allowed_addresses": trunk.allowed_addresses or "",
        "numbers": numbers,
        "last_error": trunk.last_error or "",
        "synced_at": trunk.synced_at.isoformat() if trunk.synced_at else None,
    }


class NumberConnect(BaseModel):
    number: str
    label: Optional[str] = None
    provider: Optional[str] = None


class NumberUpdate(BaseModel):
    label: Optional[str] = None
    status: Optional[str] = None
    provider: Optional[str] = None


class ConnectionUpdate(BaseModel):
    # Comma-separated IPs/CIDRs. "" clears the allowlist.
    allowed_addresses: Optional[str] = None


@router.get("/")
async def list_numbers(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)
    rows = (await db.execute(
        select(PhoneNumber).where(PhoneNumber.clinic_id == clinic_id).order_by(PhoneNumber.created_at.desc())
    )).scalars().all()
    return api_response(success=True, message="Phone numbers fetched", data=serialize_models(rows))


@router.post("/")
async def connect_number(
    payload: NumberConnect,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a number the customer holds with their own operator.

    The number is saved first and the trunk is set up afterwards, deliberately. If
    LiveKit is unreachable the customer keeps the record they just created and sees a
    "finishing setup" state, instead of losing the entry to a 502 from a third party.
    """
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    number = (payload.number or "").strip().replace(" ", "")
    if not PHONE_RE.match(number):
        return api_response(
            success=False,
            message="Enter a valid phone number in international format (e.g. +919812345678).",
            status_code=400,
        )

    allowed, used, limit = await _number_quota(db, clinic_id)
    if not allowed:
        plan_name = (await _tenant_plan(db, clinic_id))[1]
        return api_response(
            success=False,
            message=(
                f"Your {plan_name} plan includes {limit} phone number"
                f"{'' if limit == 1 else 's'} and you're already using {used}. "
                "Upgrade your plan to connect another number."
            ),
            status_code=403,
        )

    # Compare on DIGITS, not the raw string. The unique constraint is on the exact
    # text, so "+918065480571" and "918065480571" were two different rows and could
    # be claimed by two different clinics. Inbound routing resolves a dialed number
    # by trying format variants (see _did_variants in routes/calls.py), so whichever
    # variant matched first would win — letting one tenant capture another tenant's
    # calls. Normalising here makes a number claimable exactly once, platform-wide.
    if _digits(number) in await _claimed_numbers(db):
        return api_response(
            success=False,
            message="That number is already connected to an account.",
            status_code=400,
        )

    pn = PhoneNumber(
        clinic_id=clinic_id,
        number=number,
        label=(payload.label or None),
        provider=((payload.provider or "").strip() or None),
        source=SOURCE_BYO,
        # 'active' is the customer's intent, and they clearly intend this line to be
        # answered. What stops it serving traffic is verification_status, not this.
        status="active",
        verification_status=VERIFY_PENDING,
    )
    db.add(pn)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return api_response(success=False, message="That number is already connected.", status_code=400)

    clinic_name, _sub, _lim = await _tenant_row(db, clinic_id)
    sync = await _sync_trunk(db, clinic_id, clinic_name)
    trunk = await _trunk_row(db, clinic_id)

    await audit.record(
        audit.NUMBER_CONNECTED, actor=current_user, clinic_id=clinic_id,
        target_type="phone_number", target_id=pn.id,
        detail={
            "number": number, "label": pn.label, "source": SOURCE_BYO,
            "provider": pn.provider, "trunk_ready": bool(sync.get("ok")),
        },
        request=request,
    )

    if sync.get("ok"):
        message = (
            f"{number} saved. Point it at your Clarivo connection with your operator, "
            "then call it once — that first call verifies the number and switches it on."
        )
    else:
        message = f"{number} saved. We're still finishing its phone connection."
    return api_response(
        success=True,
        message=message,
        data={
            "number": serialize_model(pn),
            "connection": _trunk_payload(trunk, await _trunk_number_list(db, clinic_id)),
        },
    )


class NumberProvision(BaseModel):
    label: Optional[str] = None


@router.get("/provision-info")
async def provision_info(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What the dashboard needs to render the phone-numbers panel.

    `enabled` answers "may this account be handed a number from our own inventory?",
    which is now a compliance question and not just a credentials one — see
    settings.ALLOW_PLATFORM_NUMBERS. It is false in normal operation, so the panel
    renders the bring-your-own flow.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    allowed, used, limit = (False, 0, 0)
    if clinic_id is not None:
        allowed, used, limit = await _number_quota(db, clinic_id)
    quota = {"numbers_used": used, "numbers_included": limit}
    # Report the plan allowance on EVERY path, including the ones where automatic
    # provisioning is unavailable. The dashboard renders the same panel regardless,
    # so omitting these fields left it showing blanks.
    base = {
        **quota,
        "can_add": bool(allowed),
        # Whether the server can build SIP connections at all. When false the panel
        # tells the customer setup is incomplete rather than pretending it worked.
        "connections_enabled": livekit_sip.enabled(),
    }

    if not settings.number_provisioning_enabled:
        return api_response(success=True, message="ok", data={
            "enabled": False, "available": 0, "can_provision": False, **base,
        })

    vobiz = VobizNumbersAPI()
    result = await vobiz.list_numbers()
    if not result.get("success"):
        return api_response(success=True, message="ok", data={
            "enabled": True, "available": 0, "can_provision": False, **base,
        })

    claimed = await _claimed_numbers(db)
    available = [
        n for n in result["numbers"]
        if _is_assignable(n) and _digits(n["e164"]) not in claimed
    ]
    return api_response(success=True, message="ok", data={
        "enabled": True,
        "available": len(available),
        # can_provision is what the button should key off: it needs BOTH plan
        # headroom and a free number in the provider's inventory.
        "can_provision": bool(allowed and available),
        **base,
    })


@router.post("/provision")
async def provision_number(
    payload: NumberProvision,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Claim a number from Clarivo's OWN inventory. Off by default.

    Kept rather than deleted because it is the code path a signed channel-partner
    agreement would re-enable, and rewriting it later from nothing would be worse than
    carrying it behind a flag. But it must not run by default: it makes Clarivo the
    subscriber of record for a line another business answers, which is the arrangement
    that prompted this whole change of model.
    """
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    if not settings.ALLOW_PLATFORM_NUMBERS:
        # Recorded as a failure so that demand for this is visible, and so that if the
        # flag is ever turned on there is a record of who was asking for it.
        await audit.record(
            audit.NUMBER_PROVISIONED, actor=current_user, clinic_id=clinic_id,
            outcome="failure", detail={"reason": "platform_numbers_disabled"},
            request=request,
        )
        return api_response(
            success=False,
            message=(
                "Clarivo no longer supplies phone numbers. Connect a number you hold "
                "with your own telephony operator and forward it to your Clarivo "
                "connection — Setup shows you exactly what to give them."
            ),
            status_code=403,
        )

    if not settings.number_provisioning_enabled:
        return api_response(
            success=False,
            message="Automatic numbers aren't set up yet. Connect a number you own instead, or contact support.",
            status_code=400,
        )

    # SPEND GATE. Claiming a DID costs real money (~₹100 setup + ₹500/month) and
    # draws from a finite pool shared with other clients. Without this, any account
    # — including a free trial — could call this endpoint in a loop and run up an
    # unbounded bill. Checked before the provider is contacted so a capped clinic
    # never even triggers an assignment.
    allowed, used, limit = await _number_quota(db, clinic_id)
    if not allowed:
        plan_name = (await _tenant_plan(db, clinic_id))[1]
        # Recorded because a client repeatedly hitting the cap is a genuine
        # upgrade signal, and because spend controls should leave a trail.
        await audit.record(
            audit.NUMBER_PROVISIONED, actor=current_user, clinic_id=clinic_id,
            outcome="failure",
            detail={"reason": "plan_limit_reached", "used": used, "limit": limit,
                    "plan": plan_name},
            request=request,
        )
        return api_response(
            success=False,
            message=(
                f"Your {plan_name} plan includes {limit} phone number"
                f"{'' if limit == 1 else 's'} and you're already using {used}. "
                "Upgrade your plan to add another number, or connect a number you "
                "already own."
            ),
            status_code=403,
        )

    vobiz = VobizNumbersAPI()
    result = await vobiz.list_numbers()
    if not result.get("success"):
        return api_response(
            success=False,
            message="Could not reach the phone-number provider. Please try again in a moment.",
            status_code=502,
        )

    claimed = await _claimed_numbers(db)
    candidates = [
        n for n in result["numbers"]
        if _is_assignable(n) and _digits(n["e164"]) not in claimed
    ]
    if not candidates:
        return api_response(
            success=False,
            message="No numbers are available right now. Please contact support and we'll add one for you.",
            status_code=409,
        )

    # Prefer a number that is already pointed at our trunk (nothing to change),
    # otherwise take the first free one and route it.
    trunk_id = settings.VOBIZ_TRUNK_GROUP_ID
    candidates.sort(key=lambda n: 0 if n.get("trunk_group_id") == trunk_id else 1)
    chosen = candidates[0]
    e164 = chosen["e164"]

    if chosen.get("trunk_group_id") != trunk_id:
        assigned = await vobiz.assign_to_trunk(e164)
        if not assigned.get("success"):
            return api_response(
                success=False,
                message="Could not route that number for calls. Please try again or contact support.",
                status_code=502,
            )

    pn = PhoneNumber(
        clinic_id=clinic_id,
        number=e164,
        label=(payload.label or "").strip() or "Primary line",
        status="active",
        source=SOURCE_PLATFORM,
        # Nothing to prove: the number came out of our own account, and it routes over
        # the shared Vobiz trunk rather than a per-tenant one, so the inbound-call
        # proof that verifies a customer's own number does not apply.
        verification_status=VERIFY_VERIFIED,
        verified_at=datetime.utcnow(),
    )
    db.add(pn)
    try:
        await db.commit()
    except IntegrityError:
        # Another clinic claimed it between our read and write.
        await db.rollback()
        return api_response(
            success=False,
            message="That number was just taken. Please try again.",
            status_code=409,
        )

    logger.info(f"Provisioned {e164} for clinic {clinic_id} (trunk {trunk_id})")
    # This one costs money, so it must be attributable.
    await audit.record(
        audit.NUMBER_PROVISIONED, actor=current_user, clinic_id=clinic_id,
        target_type="phone_number", target_id=pn.id,
        detail={"number": e164, "trunk_group_id": trunk_id, "source": SOURCE_PLATFORM,
                "numbers_used_after": used + 1, "limit": limit},
        request=request,
    )
    return api_response(
        success=True,
        message=f"{e164} is ready to receive calls.",
        data=serialize_model(pn),
    )


# ----- connection details the customer gives their operator -----------------

@router.get("/connection")
@limiter.limit("30/minute")
async def get_connection(
    request: Request,  # required by slowapi for IP key extraction
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The SIP details for this tenant's trunk.

    Read-only: the trunk is created when the first number is connected, not here. A
    GET that provisions a remote resource would mean a page refresh could issue
    credentials, and rate-limited or not, that is not what a read should do.
    """
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)
    trunk = await _trunk_row(db, clinic_id)
    numbers = await _trunk_number_list(db, clinic_id) if trunk is not None else []
    return api_response(success=True, message="ok", data=_trunk_payload(trunk, numbers))


@router.post("/connection")
@limiter.limit("6/minute")
async def create_or_repair_connection(
    request: Request,  # required by slowapi for IP key extraction
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create this tenant's SIP connection, or retry a failed setup.

    Idempotent: it reuses the existing trunk row and credentials if there is one, and
    only pushes the current number list. It exists because the normal trigger — adding
    a number — is a one-shot. If LiveKit was unreachable at that moment the number is
    saved and the connection is left `pending`, and without this the only way to retry
    would be to delete the number and add it again.
    """
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    clinic_name, _sub, _lim = await _tenant_row(db, clinic_id)
    existed = await _trunk_row(db, clinic_id) is not None
    result = await _sync_trunk(db, clinic_id, clinic_name)
    trunk = await _trunk_row(db, clinic_id)

    if not existed and trunk is not None:
        await audit.record(
            audit.TRUNK_CREATED, actor=current_user, clinic_id=clinic_id,
            target_type="sip_trunk", target_id=trunk.id,
            outcome="success" if result.get("ok") else "failure",
            detail={"livekit_trunk_id": trunk.livekit_trunk_id or ""},
            request=request,
        )

    numbers = await _trunk_number_list(db, clinic_id)
    payload = _trunk_payload(trunk, numbers)
    if result.get("ok"):
        return api_response(success=True, message="Your connection is ready.", data=payload)
    # Not an error response: the row exists and the dashboard needs to render its
    # pending state with the reason. Returning 502 here would leave the panel blank.
    return api_response(
        success=True,
        message=result.get("error") or "We're still finishing this connection.",
        data=payload,
    )


@router.put("/connection")
@limiter.limit("10/minute")
async def update_connection(
    request: Request,  # required by slowapi for IP key extraction
    payload: ConnectionUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set or clear the operator IP allowlist on this tenant's trunk.

    Optional, and left empty by default: it is the control that turns the credentials
    from a shared secret into a shared secret usable only from known hosts, but a wrong
    value silently breaks every inbound call for this tenant, and most customers do not
    know their operator's signalling addresses.
    """
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)
    trunk = await _trunk_row(db, clinic_id)
    if trunk is None:
        return api_response(
            success=False,
            message="Connect a phone number first — your connection is created with it.",
            status_code=400,
        )

    if payload.allowed_addresses is not None:
        cleaned = ", ".join(livekit_sip.parse_allowed_addresses(payload.allowed_addresses))
        trunk.allowed_addresses = cleaned or None
        trunk.updated_at = datetime.utcnow()
        await db.commit()
        if trunk.livekit_trunk_id:
            clinic_name, _sub, _lim = await _tenant_row(db, clinic_id)
            result = await livekit_sip.replace_trunk(
                trunk_id=trunk.livekit_trunk_id,
                clinic_id=clinic_id,
                clinic_name=clinic_name,
                numbers=await _trunk_number_list(db, clinic_id),
                auth_username=trunk.auth_username,
                auth_password=trunk.auth_password,
                allowed_addresses=trunk.allowed_addresses,
            )
            if not result.get("ok"):
                return api_response(success=False, message=result.get("error") or "Could not update.", status_code=502)

    await audit.record(
        audit.TRUNK_UPDATED, actor=current_user, clinic_id=clinic_id,
        target_type="sip_trunk", target_id=trunk.id,
        detail={"allowed_addresses": trunk.allowed_addresses or ""},
        request=request,
    )
    numbers = await _trunk_number_list(db, clinic_id)
    return api_response(success=True, message="Connection updated", data=_trunk_payload(trunk, numbers))


@router.post("/connection/rotate")
@limiter.limit("3/minute")
async def rotate_connection(
    request: Request,  # required by slowapi for IP key extraction
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Issue new digest credentials for this tenant's trunk.

    Immediately disruptive, and that is the intended behaviour: the old credentials
    stop working as soon as this returns, so calls stay down until the customer updates
    their operator. Rate limited hard — repeatedly rotating is indistinguishable from
    an outage from the customer's side.

    The new secret is only persisted if LiveKit accepted it. Storing it first would let
    a failed call leave the database and LiveKit disagreeing, and the dashboard would
    then show a password that does not work.
    """
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)
    trunk = await _trunk_row(db, clinic_id)
    if trunk is None:
        return api_response(
            success=False,
            message="Connect a phone number first — your connection is created with it.",
            status_code=400,
        )

    username, password = livekit_sip.generate_credentials()
    if trunk.livekit_trunk_id:
        clinic_name, _sub, _lim = await _tenant_row(db, clinic_id)
        result = await livekit_sip.replace_trunk(
            trunk_id=trunk.livekit_trunk_id,
            clinic_id=clinic_id,
            clinic_name=clinic_name,
            numbers=await _trunk_number_list(db, clinic_id),
            auth_username=username,
            auth_password=password,
            allowed_addresses=trunk.allowed_addresses,
        )
        if not result.get("ok"):
            return api_response(
                success=False,
                message=result.get("error") or "Could not rotate the credentials.",
                status_code=502,
            )

    trunk.auth_username = username
    trunk.auth_password = password
    trunk.updated_at = datetime.utcnow()
    await db.commit()

    # No credential values in the detail — audit._scrub would redact them anyway, and
    # relying on the backstop instead of not sending them is how it stops being a
    # backstop.
    await audit.record(
        audit.TRUNK_CREDENTIALS_ROTATED, actor=current_user, clinic_id=clinic_id,
        target_type="sip_trunk", target_id=trunk.id,
        detail={"livekit_trunk_id": trunk.livekit_trunk_id or ""},
        request=request,
    )
    numbers = await _trunk_number_list(db, clinic_id)
    return api_response(
        success=True,
        message="New credentials issued. Update them with your operator — calls will fail until you do.",
        data=_trunk_payload(trunk, numbers),
    )


@router.put("/{number_id}")
async def update_number(
    number_id: str,
    payload: NumberUpdate,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    nid = to_uuid(number_id)
    if nid is None:
        return api_response(success=False, message="Phone number not found", status_code=404)

    pn = (await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == nid, PhoneNumber.clinic_id == clinic_id)
    )).scalar_one_or_none()
    if not pn:
        return api_response(success=False, message="Phone number not found", status_code=404)

    if payload.label is not None:
        pn.label = payload.label or None
    if payload.provider is not None:
        pn.provider = (payload.provider or "").strip() or None
    status_changed = False
    if payload.status is not None:
        if payload.status not in ("active", "inactive"):
            return api_response(success=False, message="Invalid status", status_code=400)
        status_changed = pn.status != payload.status
        pn.status = payload.status
    await db.commit()

    # Deactivating has to reach LiveKit, or the number stays on the trunk and calls
    # keep arriving for a line the customer believes they switched off.
    if status_changed:
        clinic_name, _sub, _lim = await _tenant_row(db, clinic_id)
        await _sync_trunk(db, clinic_id, clinic_name)

    await audit.record(
        audit.NUMBER_UPDATED, actor=current_user, clinic_id=clinic_id,
        target_type="phone_number", target_id=pn.id,
        detail={"number": pn.number, "status": pn.status, "label": pn.label},
        request=request,
    )
    return api_response(success=True, message="Phone number updated", data=serialize_model(pn))


@router.delete("/{number_id}")
async def remove_number(
    number_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    nid = to_uuid(number_id)
    if nid is None:
        return api_response(success=False, message="Phone number not found", status_code=404)

    pn = (await db.execute(
        select(PhoneNumber).where(PhoneNumber.id == nid, PhoneNumber.clinic_id == clinic_id)
    )).scalar_one_or_none()
    if not pn:
        return api_response(success=False, message="Phone number not found", status_code=404)

    removed_number = pn.number
    removed_source = pn.source
    await db.delete(pn)
    await db.commit()

    # Take it off the trunk too. The trunk row itself is kept even when this was the
    # last number: the credentials are what the customer configured at their operator,
    # and re-issuing them because they briefly had no numbers would break a working
    # setup for no reason.
    clinic_name, _sub, _lim = await _tenant_row(db, clinic_id)
    await _sync_trunk(db, clinic_id, clinic_name)

    # Removing a number silently breaks inbound calls for that line, so "who
    # removed it and when" needs to be answerable.
    await audit.record(
        audit.NUMBER_REMOVED, actor=current_user, clinic_id=clinic_id,
        target_type="phone_number", target_id=nid,
        detail={"number": removed_number, "source": removed_source},
        request=request,
    )

    if removed_source == SOURCE_PLATFORM:
        # Nothing to undo at Vobiz: their REST API exposes assign but no unassign
        # (see integrations/vobiz/client.py), so a platform-provisioned DID stays
        # pointed at our shared trunk and keeps billing until someone removes it in
        # the Vobiz dashboard. Logged rather than hidden, because the alternative is
        # paying for numbers nobody uses.
        logger.warning(
            f"{removed_number} was platform-provisioned; it remains assigned to the "
            f"Vobiz trunk and must be released manually in the Vobiz dashboard."
        )

    return api_response(success=True, message="Phone number removed")
