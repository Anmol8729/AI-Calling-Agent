"""
Platform admin endpoints (super-admin only).

Lets a platform operator (email in SUPERADMIN_EMAILS) view every client tenant
and assign its subscription plan and/or a custom monthly call allowance —
without touching the database directly. There is no payment gateway; plan
assignment is a deliberate operator action.

All routes require the require_superadmin dependency, so regular tenant users
(clinic/agency owners) get 403 even if they discover the URL.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.routes.auth import require_superadmin
from backend.services.plans import list_plans, get_plan, effective_call_limit, is_valid_plan
from backend.services import diagnostics
from backend.models import Tenant, CallLog, User, UpgradeRequest, DemoRequest
from backend.utils.helpers import api_response, to_uuid

logger = logging.getLogger("admin-router")
router = APIRouter(prefix="/admin", tags=["Admin"])


class TenantPlanUpdate(BaseModel):
    # Plan key (free/starter/growth/scale). Omit to leave unchanged.
    subscription: Optional[str] = None
    # Custom monthly allowance override. Send a positive int to set, or 0/null
    # to clear the override (fall back to the plan default). Omit to leave as-is.
    monthly_call_limit: Optional[int] = Field(default=None, ge=0)


def _tenant_view(t: Tenant, used: int) -> dict:
    plan = get_plan(t.subscription)
    return {
        "id": str(t.id),
        "name": t.name,
        "industry": t.industry,
        "subscription": t.subscription,
        "planName": plan["name"],
        "monthlyCallLimit": effective_call_limit(t.subscription, t.monthly_call_limit),
        "customAllowance": t.monthly_call_limit,
        "callsUsed": used,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
    }


async def _month_usage_map(db: AsyncSession) -> dict:
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    rows = (await db.execute(
        select(CallLog.clinic_id, func.count())
        .where(CallLog.created_at >= month_start, CallLog.clinic_id.isnot(None))
        .group_by(CallLog.clinic_id)
    )).all()
    return {cid: count for cid, count in rows}


@router.get("/plans")
async def admin_plans(current_user: dict = Depends(require_superadmin)):
    return api_response(success=True, message="Plans fetched", data=list_plans())


@router.get("/diagnostics")
async def admin_diagnostics(
    current_user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """Readiness check for each integration (DB, Deepgram, MiniMax, Vobiz, WhatsApp, email)."""
    return api_response(success=True, message="Diagnostics", data=await diagnostics.run_all(db))


@router.get("/tenants")
async def list_tenants(
    current_user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    tenants = (await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))).scalars().all()
    usage = await _month_usage_map(db)

    # Team size per tenant (single grouped query).
    team_rows = (await db.execute(
        select(User.clinic_id, func.count()).where(User.clinic_id.isnot(None)).group_by(User.clinic_id)
    )).all()
    team_map = {cid: count for cid, count in team_rows}

    data = []
    for t in tenants:
        view = _tenant_view(t, usage.get(t.id, 0))
        view["teamSize"] = team_map.get(t.id, 0)
        data.append(view)
    return api_response(success=True, message="Tenants fetched", data=data)


@router.put("/tenants/{tenant_id}/plan")
async def set_tenant_plan(
    tenant_id: str,
    payload: TenantPlanUpdate,
    current_user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    tid = to_uuid(tenant_id)
    if tid is None:
        return api_response(success=False, message="Invalid tenant id", status_code=400)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == tid))).scalar_one_or_none()
    if tenant is None:
        return api_response(success=False, message="Tenant not found", status_code=404)

    data = payload.dict(exclude_unset=True)
    if "subscription" in data:
        key = (data["subscription"] or "").strip().lower()
        if not is_valid_plan(key):
            return api_response(success=False, message=f"Unknown plan '{key}'", status_code=400)
        tenant.subscription = key
    if "monthly_call_limit" in data:
        val = data["monthly_call_limit"]
        tenant.monthly_call_limit = int(val) if (val and val > 0) else None

    await db.commit()
    await db.refresh(tenant)

    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    used = (await db.execute(
        select(func.count()).select_from(CallLog).where(
            CallLog.clinic_id == tid, CallLog.created_at >= month_start
        )
    )).scalar() or 0

    logger.info(f"Super-admin {current_user.get('email')} updated tenant {tid} plan -> "
                f"{tenant.subscription}, custom_limit={tenant.monthly_call_limit}")
    return api_response(success=True, message="Plan updated", data=_tenant_view(tenant, used))


# ----- Upgrade requests -----------------------------------------------------

class UpgradeRequestAction(BaseModel):
    action: str = Field(..., description="approve | reject")


@router.get("/upgrade-requests")
async def list_upgrade_requests(
    current_user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(UpgradeRequest).order_by(UpgradeRequest.created_at.desc()).limit(100)
    )).scalars().all()

    tenant_ids = {r.clinic_id for r in rows}
    tmap = {}
    if tenant_ids:
        trows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(tenant_ids)))).all()
        tmap = {tid: name for tid, name in trows}

    data = [{
        "id": str(r.id),
        "clinicId": str(r.clinic_id),
        "business": tmap.get(r.clinic_id, "—"),
        "currentPlan": r.current_plan,
        "requestedPlan": r.requested_plan,
        "requestedPlanName": get_plan(r.requested_plan)["name"],
        "note": r.note,
        "status": r.status,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    return api_response(success=True, message="Upgrade requests fetched", data=data)


@router.put("/upgrade-requests/{request_id}")
async def resolve_upgrade_request(
    request_id: str,
    payload: UpgradeRequestAction,
    current_user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    rid = to_uuid(request_id)
    if rid is None:
        return api_response(success=False, message="Invalid request id", status_code=400)

    req = (await db.execute(select(UpgradeRequest).where(UpgradeRequest.id == rid))).scalar_one_or_none()
    if req is None:
        return api_response(success=False, message="Upgrade request not found", status_code=404)
    if req.status != "pending":
        return api_response(success=False, message=f"Request already {req.status}", status_code=400)

    action = (payload.action or "").strip().lower()
    if action == "approve":
        if not is_valid_plan(req.requested_plan):
            return api_response(success=False, message="Requested plan is no longer valid", status_code=400)
        tenant = (await db.execute(select(Tenant).where(Tenant.id == req.clinic_id))).scalar_one_or_none()
        if tenant is not None:
            tenant.subscription = req.requested_plan
        req.status = "approved"
    elif action == "reject":
        req.status = "rejected"
    else:
        return api_response(success=False, message="Invalid action (use approve or reject)", status_code=400)

    req.resolved_at = datetime.utcnow()
    await db.commit()
    logger.info(f"Super-admin {current_user.get('email')} {req.status} upgrade request {rid}")
    return api_response(success=True, message=f"Request {req.status}", data={"id": str(rid), "status": req.status})


# ----- Demo / callback leads ------------------------------------------------

@router.get("/demo-requests")
async def list_demo_requests(
    current_user: dict = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    """List all landing-page callback leads, newest first."""
    rows = (await db.execute(
        select(DemoRequest).order_by(DemoRequest.created_at.desc()).limit(200)
    )).scalars().all()
    data = [{
        "id": str(r.id),
        "name": r.name,
        "phone": r.phone,
        "email": r.email,
        "note": r.note,
        "status": r.status,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    return api_response(success=True, message="Demo requests fetched", data=data)
