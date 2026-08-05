import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.services import plans, audit
from backend.routes.auth import get_current_user
from backend.models import PhoneNumber, Tenant
from backend.config.settings import settings
from backend.integrations.vobiz.client import VobizNumbersAPI
from backend.utils.helpers import api_response, serialize_model, serialize_models, to_uuid

logger = logging.getLogger("phone-numbers-router")
router = APIRouter(prefix="/phone-numbers", tags=["Phone Numbers"])

MANAGER_ROLES = {"doctor", "admin"}
# Lenient E.164-style check: optional +, leading non-zero digit, 7-16 digits total.
PHONE_RE = re.compile(r"^\+?[1-9]\d{6,15}$")


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


async def _tenant_plan(db: AsyncSession, clinic_id) -> tuple:
    """(plan_key, plan_name, number_limit_override) for a clinic."""
    row = (await db.execute(
        select(Tenant.subscription, Tenant.number_limit).where(Tenant.id == clinic_id)
    )).first()
    key = (row[0] if row else None) or plans.DEFAULT_PLAN_KEY
    override = row[1] if row else None
    return key, plans.get_plan(key)["name"], override


async def _number_quota(db: AsyncSession, clinic_id) -> tuple:
    """(is_allowed_another, currently_used, limit) for this clinic's DIDs.

    A spend control, not a feature flag — see plans.included_numbers for why.
    """
    key, _name, override = await _tenant_plan(db, clinic_id)
    limit = plans.included_numbers(key, override)
    used = (await db.execute(
        select(func.count()).select_from(PhoneNumber).where(PhoneNumber.clinic_id == clinic_id)
    )).scalar() or 0
    return (used < limit), int(used), int(limit)


class NumberConnect(BaseModel):
    number: str
    label: Optional[str] = None


class NumberUpdate(BaseModel):
    label: Optional[str] = None
    status: Optional[str] = None


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
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    number = (payload.number or "").strip().replace(" ", "")
    if not PHONE_RE.match(number):
        return api_response(
            success=False,
            message="Enter a valid phone number in international format (e.g. +14155550100).",
            status_code=400,
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

    pn = PhoneNumber(clinic_id=clinic_id, number=number, label=(payload.label or None), status="active")
    db.add(pn)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return api_response(success=False, message="That number is already connected.", status_code=400)

    await audit.record(
        audit.NUMBER_CONNECTED, actor=current_user, clinic_id=clinic_id,
        target_type="phone_number", target_id=pn.id,
        detail={"number": number, "label": pn.label, "source": "bring_your_own"},
        request=request,
    )
    return api_response(success=True, message="Phone number connected", data=serialize_model(pn))


class NumberProvision(BaseModel):
    label: Optional[str] = None


@router.get("/provision-info")
async def provision_info(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Whether one-click provisioning is available, and how many numbers are free.

    Lets the dashboard show/enable the "Get a number" button without the client
    having to attempt a provision to find out.
    """
    # Report the plan allowance on EVERY path, including the ones where automatic
    # provisioning is unavailable. The dashboard renders the same panel regardless,
    # so omitting these fields left it showing blanks.
    clinic_id = to_uuid(current_user.get("clinic_id"))
    allowed, used, limit = (False, 0, 0)
    if clinic_id is not None:
        allowed, used, limit = await _number_quota(db, clinic_id)
    quota = {"numbers_used": used, "numbers_included": limit}

    if not settings.number_provisioning_enabled:
        return api_response(success=True, message="ok", data={
            "enabled": False, "available": 0, "can_provision": False, **quota,
        })

    vobiz = VobizNumbersAPI()
    result = await vobiz.list_numbers()
    if not result.get("success"):
        return api_response(success=True, message="ok", data={
            "enabled": True, "available": 0, "can_provision": False, **quota,
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
        **quota,
    })


@router.post("/provision")
async def provision_number(
    payload: NumberProvision,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One-click: claim a number from the Vobiz inventory and make it call-ready.

    Steps: pick a number that no clinic has claimed yet -> assign it to our
    inbound trunk (whose destination is the LiveKit SIP URI) -> save it against
    this clinic. After this the DID routes straight to the voice agent, which
    resolves the clinic from the dialed number, so the caller reaches the right
    business with no further setup.
    """
    _require_manager(current_user)
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

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
        detail={"number": e164, "trunk_group_id": trunk_id,
                "numbers_used_after": used + 1, "limit": limit},
        request=request,
    )
    return api_response(
        success=True,
        message=f"{e164} is ready to receive calls.",
        data=serialize_model(pn),
    )


@router.put("/{number_id}")
async def update_number(
    number_id: str,
    payload: NumberUpdate,
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
    if payload.status is not None:
        if payload.status not in ("active", "inactive"):
            return api_response(success=False, message="Invalid status", status_code=400)
        pn.status = payload.status
    await db.commit()
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
    await db.delete(pn)
    await db.commit()
    # Removing a number silently breaks inbound calls for that line, so "who
    # removed it and when" needs to be answerable.
    await audit.record(
        audit.NUMBER_REMOVED, actor=current_user, clinic_id=clinic_id,
        target_type="phone_number", target_id=nid,
        detail={"number": removed_number},
        request=request,
    )
    return api_response(success=True, message="Phone number removed")
