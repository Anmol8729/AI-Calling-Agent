import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.db import get_db
from backend.routes.auth import get_current_user
from backend.models import CallLog, Appointment, Patient, User, PhoneNumber, Tenant
from backend.utils.helpers import api_response, to_uuid

logger = logging.getLogger("stats-router")
router = APIRouter(prefix="/stats", tags=["Stats"])


def _fmt_duration(seconds) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60}m {seconds % 60}s"


@router.get("/overview")
async def overview(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    from backend.services.demo_data import get_demo_overview, DEMO_CLINIC_ID
    if db is None or str(clinic_id) == DEMO_CLINIC_ID:
        return api_response(success=True, message="Overview fetched", data=get_demo_overview())

    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    week_start = now - timedelta(days=7)

    async def scalar(stmt):
        return (await db.execute(stmt)).scalar() or 0

    total_calls = await scalar(select(func.count()).select_from(CallLog).where(CallLog.clinic_id == clinic_id))
    calls_today = await scalar(select(func.count()).select_from(CallLog).where(CallLog.clinic_id == clinic_id, CallLog.created_at >= today_start))
    calls_7d = await scalar(select(func.count()).select_from(CallLog).where(CallLog.clinic_id == clinic_id, CallLog.created_at >= week_start))
    active_calls = await scalar(select(func.count()).select_from(CallLog).where(CallLog.clinic_id == clinic_id, CallLog.status == "active"))
    avg_duration = await scalar(select(func.coalesce(func.avg(CallLog.duration), 0)).where(CallLog.clinic_id == clinic_id))
    total_seconds = await scalar(select(func.coalesce(func.sum(CallLog.duration), 0)).where(CallLog.clinic_id == clinic_id))

    total_appointments = await scalar(select(func.count()).select_from(Appointment).where(Appointment.clinic_id == clinic_id))
    scheduled_appointments = await scalar(select(func.count()).select_from(Appointment).where(Appointment.clinic_id == clinic_id, Appointment.status == "scheduled"))
    total_contacts = await scalar(select(func.count()).select_from(Patient).where(Patient.clinic_id == clinic_id))
    team_size = await scalar(select(func.count()).select_from(User).where(User.clinic_id == clinic_id))
    numbers_connected = await scalar(select(func.count()).select_from(PhoneNumber).where(PhoneNumber.clinic_id == clinic_id))

    tenant = (await db.execute(select(Tenant).where(Tenant.id == clinic_id))).scalar_one_or_none()
    plan = (tenant.subscription if tenant else "free") or "free"

    outcome_rows = (await db.execute(
        select(CallLog.status, func.count()).where(CallLog.clinic_id == clinic_id).group_by(CallLog.status)
    )).all()
    outcomes = [{"status": (s or "unknown"), "count": c} for s, c in outcome_rows]

    # Daily call volume for the last 7 calendar days (zero-filled).
    daily_rows = (await db.execute(
        select(func.date(CallLog.created_at), func.count())
        .where(CallLog.clinic_id == clinic_id, CallLog.created_at >= today_start - timedelta(days=6))
        .group_by(func.date(CallLog.created_at))
    )).all()
    daily_map = {}
    for d, c in daily_rows:
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        daily_map[key] = c
    daily = []
    for i in range(6, -1, -1):
        day = (today_start - timedelta(days=i)).date().isoformat()
        daily.append({"date": day, "count": daily_map.get(day, 0)})

    recent_rows = (await db.execute(
        select(CallLog).where(CallLog.clinic_id == clinic_id).order_by(CallLog.created_at.desc()).limit(8)
    )).scalars().all()
    recent = [{
        "id": str(r.id),
        "customer": r.caller_name or r.phone or "Unknown",
        "phone": r.phone,
        "direction": r.direction or "inbound",
        "duration": int(r.duration or 0),
        "status": r.status or "unknown",
        "date": r.created_at.isoformat() if r.created_at else None,
    } for r in recent_rows]

    data = {
        "totals": {
            "calls": total_calls,
            "appointments": total_appointments,
            "scheduledAppointments": scheduled_appointments,
            "contacts": total_contacts,
            "team": team_size,
            "numbers": numbers_connected,
        },
        "calls": {
            "today": calls_today,
            "last7Days": calls_7d,
            "active": active_calls,
            "avgDurationSec": int(avg_duration),
            "totalMinutes": round(total_seconds / 60, 1),
        },
        "outcomes": outcomes,
        "daily": daily,
        "recent": recent,
        "plan": plan,
    }
    return api_response(success=True, message="Overview fetched", data=data)


@router.get("/live")
async def live_calls(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)
    rows = (await db.execute(
        select(CallLog)
        .where(CallLog.clinic_id == clinic_id, CallLog.status == "active")
        .order_by(CallLog.created_at.desc())
    )).scalars().all()
    data = [{
        "id": str(r.id),
        "caller": r.caller_name or r.phone or "Unknown",
        "phone": r.phone,
        "direction": r.direction or "inbound",
        "startedAt": r.created_at.isoformat() if r.created_at else None,
        "turns": len(r.transcript or []),
    } for r in rows]
    return api_response(success=True, message="Live calls fetched", data=data)


@router.get("/funnel")
async def funnel(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Conversion funnel over the last 30 days: calls -> answered -> booked,
    plus leads captured and transfers, with the derived rates."""
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    period_days = 30
    since = datetime.utcnow() - timedelta(days=period_days)

    async def scalar(stmt):
        return (await db.execute(stmt)).scalar() or 0

    calls = await scalar(select(func.count()).select_from(CallLog).where(
        CallLog.clinic_id == clinic_id, CallLog.created_at >= since))
    answered = await scalar(select(func.count()).select_from(CallLog).where(
        CallLog.clinic_id == clinic_id, CallLog.created_at >= since,
        CallLog.status.in_(["completed", "transferred", "active"])))
    transferred = await scalar(select(func.count()).select_from(CallLog).where(
        CallLog.clinic_id == clinic_id, CallLog.created_at >= since,
        CallLog.status == "transferred"))
    appointments = await scalar(select(func.count()).select_from(Appointment).where(
        Appointment.clinic_id == clinic_id, Appointment.created_at >= since))
    leads = await scalar(select(func.count()).select_from(Patient).where(
        Patient.clinic_id == clinic_id, Patient.created_at >= since))

    def rate(n):
        return round((n / calls) * 100, 1) if calls > 0 else 0.0

    data = {
        "periodDays": period_days,
        "calls": calls,
        "answered": answered,
        "transferred": transferred,
        "appointments": appointments,
        "leads": leads,
        "answerRate": rate(answered),
        "conversionRate": rate(appointments),
        "transferRate": rate(transferred),
    }
    return api_response(success=True, message="Funnel fetched", data=data)


@router.get("/onboarding")
async def onboarding(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Setup checklist state for the tenant, derived from existing data."""
    clinic_id = to_uuid(current_user.get("clinic_id"))
    from backend.services.demo_data import get_demo_onboarding, DEMO_CLINIC_ID
    if db is None or str(clinic_id) == DEMO_CLINIC_ID:
        return api_response(success=True, message="Onboarding state fetched", data=get_demo_onboarding())

    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == clinic_id))).scalar_one_or_none()

    async def scalar(stmt):
        return (await db.execute(stmt)).scalar() or 0

    calls = await scalar(select(func.count()).select_from(CallLog).where(CallLog.clinic_id == clinic_id))
    numbers = await scalar(select(func.count()).select_from(PhoneNumber).where(PhoneNumber.clinic_id == clinic_id))

    steps = {
        "industry": bool(tenant and tenant.industry),
        "knowledgeBase": bool(tenant and (tenant.knowledge_base or "").strip()),
        "phoneNumber": bool(numbers > 0 or (tenant and tenant.did)),
        "agentConfigured": bool(tenant and (tenant.voice or tenant.language)),
        "firstCall": calls > 0,
    }
    data = {**steps, "complete": all(steps.values())}
    return api_response(success=True, message="Onboarding state fetched", data=data)
