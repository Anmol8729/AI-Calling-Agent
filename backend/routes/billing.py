"""
Billing / plan + usage + self-serve upgrade endpoints.

Plans are defined by monthly call volume (see services/plans.py). This exposes:
  GET  /billing/plans            -> the plan catalog (for the pricing comparison)
  GET  /billing/summary          -> current plan, allowance, this-month usage,
                                    and whether online payments are available.
  POST /billing/upgrade-request  -> client asks to move to another plan (no
                                    payment); a super-admin approves it.
  POST /billing/checkout         -> create a Razorpay order for a priced plan.
  POST /billing/verify           -> verify the checkout signature and, if valid,
                                    upgrade the tenant's plan + record payment.
  POST /billing/webhook          -> signed Razorpay webhook (source of truth for
                                    payment.captured); no auth, signature-verified.

Money rules: amounts are always computed server-side from the plan price, the
plan being purchased is read from the stored order (never the client), and the
payment signature is verified before any upgrade.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.services.db import get_db
from backend.services import billing_period
from backend.routes.auth import get_current_user
from backend.services.plans import list_plans, get_plan, effective_call_limit, is_valid_plan
from backend.services.email import send_email
from backend.services.razorpay_client import (
    create_order,
    verify_payment_signature,
    verify_webhook_signature,
)
from backend.models import CallLog, Tenant, UpgradeRequest, Payment
from backend.utils.helpers import api_response, to_uuid

logger = logging.getLogger("billing-router")
router = APIRouter(prefix="/billing", tags=["Billing"])


def _month_start() -> datetime:
    """Kept as a thin alias so existing call sites read unchanged.

    The arithmetic moved to services/billing_period.py, which anchors the month to
    the BILLING timezone rather than UTC. Anchoring to UTC meant that for the first
    5h30m of every month, calls made that morning in India were billed to the month
    that had already closed.
    """
    return billing_period.month_start_utc()





async def _calls_this_month(db: AsyncSession, clinic_id) -> int:
    return (await db.execute(
        select(func.count()).select_from(CallLog).where(
            CallLog.clinic_id == clinic_id, CallLog.created_at >= _month_start()
        )
    )).scalar() or 0


# ----- Plan catalog + usage -------------------------------------------------

@router.get("/plans")
async def get_plans(current_user: dict = Depends(get_current_user)):
    return api_response(success=True, message="Plans fetched", data=list_plans())


@router.get("/summary")
async def billing_summary(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == clinic_id))).scalar_one_or_none()
    if tenant is None:
        return api_response(success=False, message="Tenant not found", status_code=404)

    plan = get_plan(tenant.subscription)
    limit = effective_call_limit(tenant.subscription, tenant.monthly_call_limit)
    used = await _calls_this_month(db, clinic_id)
    remaining = max(limit - used, 0)
    percent = round(min(used / limit, 1.0) * 100, 1) if limit > 0 else 0.0
    now = datetime.utcnow()

    data = {
        "plan": {
            "key": plan["key"],
            "name": plan["name"],
            "priceInr": plan["price_inr"],
            "description": plan.get("description"),
            "customAllowance": bool(tenant.monthly_call_limit and tenant.monthly_call_limit > 0
                                    and tenant.monthly_call_limit != plan["monthly_call_limit"]),
        },
        "usage": {
            "monthlyCallLimit": limit,
            "callsUsed": used,
            "callsRemaining": remaining,
            "percentUsed": percent,
            "periodStart": _month_start().isoformat(),
            "periodLabel": billing_period.month_label(),
        },
        "paymentsEnabled": settings.payments_enabled,
    }
    return api_response(success=True, message="Billing summary fetched", data=data)


# ----- Upgrade request (no payment) -----------------------------------------

class UpgradeRequestBody(BaseModel):
    plan: str
    note: Optional[str] = None


@router.post("/upgrade-request")
async def request_upgrade(
    body: UpgradeRequestBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    key = (body.plan or "").strip().lower()
    if not is_valid_plan(key):
        return api_response(success=False, message=f"Unknown plan '{key}'", status_code=400)

    tenant = (await db.execute(select(Tenant).where(Tenant.id == clinic_id))).scalar_one_or_none()
    if tenant is None:
        return api_response(success=False, message="Tenant not found", status_code=404)

    db.add(UpgradeRequest(
        clinic_id=clinic_id,
        requested_by=str(current_user.get("id")),
        current_plan=tenant.subscription,
        requested_plan=key,
        note=(body.note or "").strip() or None,
        status="pending",
    ))
    await db.commit()

    # Notify platform super-admins (best-effort; never fail the request on email).
    admins = [e.strip() for e in (settings.SUPERADMIN_EMAILS or "").split(",") if e.strip()]
    if admins:
        plan_name = get_plan(key)["name"]
        subject = f"Upgrade request: {tenant.name} -> {plan_name}"
        text = (
            f"{tenant.name} ({current_user.get('email')}) requested an upgrade "
            f"to the {plan_name} plan.\n\nNote: {body.note or '-'}\n\n"
            f"Review it in the dashboard Admin page."
        )
        for email in admins:
            try:
                await asyncio.to_thread(send_email, email, subject, text)
            except Exception as e:
                logger.warning(f"Could not email super-admin {email}: {e}")

    return api_response(success=True, message="Upgrade request submitted. Our team will get in touch.")


# ----- Razorpay checkout ----------------------------------------------------

class CheckoutBody(BaseModel):
    plan: str


@router.post("/checkout")
async def checkout(
    body: CheckoutBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.payments_enabled:
        return api_response(success=False, message="Online payments are not enabled.", status_code=400)

    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    key = (body.plan or "").strip().lower()
    if not is_valid_plan(key):
        return api_response(success=False, message=f"Unknown plan '{key}'", status_code=400)

    plan = get_plan(key)
    price = plan["price_inr"]
    if not price or price <= 0:
        return api_response(
            success=False,
            message="This plan has no online price set. Please use Request upgrade.",
            status_code=400,
        )

    tenant = (await db.execute(select(Tenant).where(Tenant.id == clinic_id))).scalar_one_or_none()
    receipt = f"rcpt_{uuid.uuid4().hex[:20]}"  # Razorpay receipt max 40 chars
    try:
        order = await create_order(price, receipt, notes={"clinic_id": str(clinic_id), "plan": key})
    except Exception as e:
        logger.error(f"Razorpay order failed: {e}")
        return api_response(success=False, message="Could not start payment. Please try again.", status_code=502)

    db.add(Payment(
        clinic_id=clinic_id,
        plan_key=key,
        amount_inr=int(price),
        currency=order.get("currency", "INR"),
        razorpay_order_id=order["id"],
        status="created",
    ))
    await db.commit()

    return api_response(success=True, message="Order created", data={
        "orderId": order["id"],
        "amount": order["amount"],          # paise
        "currency": order.get("currency", "INR"),
        "keyId": settings.RAZORPAY_KEY_ID,  # public key, safe for the browser
        "planKey": key,
        "planName": plan["name"],
        "businessName": tenant.name if tenant else "",
        "email": current_user.get("email", ""),
    })


class VerifyBody(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


async def _activate_paid_plan(db: AsyncSession, payment: Payment, payment_id: str):
    """Mark a payment paid and upgrade the tenant's plan (idempotent)."""
    if payment.status == "paid":
        return
    payment.status = "paid"
    payment.razorpay_payment_id = payment_id
    payment.paid_at = datetime.utcnow()
    tenant = (await db.execute(select(Tenant).where(Tenant.id == payment.clinic_id))).scalar_one_or_none()
    if tenant is not None:
        tenant.subscription = payment.plan_key
    await db.commit()


@router.post("/verify")
async def verify_payment(
    body: VerifyBody,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with user", status_code=400)

    payment = (await db.execute(
        select(Payment).where(Payment.razorpay_order_id == body.razorpay_order_id)
    )).scalar_one_or_none()
    if payment is None or payment.clinic_id != clinic_id:
        return api_response(success=False, message="Unknown order", status_code=400)

    if payment.status == "paid":
        return api_response(success=True, message="Payment already confirmed", data={"plan": payment.plan_key})

    if not verify_payment_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        # Deliberately does NOT mark the payment failed. A bad signature only proves
        # THIS request was not signed by Razorpay — it says nothing about the real
        # payment, which may still be in progress. Writing "failed" here let anyone
        # in the tenant who knew an order id force a pending order into a terminal
        # state, and the genuine webhook would then find it already closed.
        # The signed webhook is the authority on payment outcome.
        logger.warning(
            f"Rejected an unsigned verify for order {body.razorpay_order_id} "
            f"(clinic {clinic_id}). Payment status left untouched at "
            f"{payment.status!r} — only the signed webhook may change it."
        )
        await audit.record(
            audit.BILLING_PAYMENT_FAILED, actor=current_user, clinic_id=clinic_id,
            target_type="payment", target_id=payment.id, outcome="failure",
            detail={"reason": "invalid_signature", "order_id": body.razorpay_order_id},
        )
        return api_response(success=False, message="Payment verification failed", status_code=400)

    await _activate_paid_plan(db, payment, body.razorpay_payment_id)
    logger.info(f"Payment verified for clinic {clinic_id}; plan -> {payment.plan_key}")
    return api_response(success=True, message="Payment successful. Your plan is upgraded.", data={"plan": payment.plan_key})


@router.post("/webhook")
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Razorpay server-to-server webhook. Signature-verified; no user auth."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook_signature(body, signature):
        return api_response(success=False, message="Invalid signature", status_code=400)

    try:
        event = json.loads(body)
    except (ValueError, TypeError):
        return api_response(success=False, message="Invalid payload", status_code=400)

    if event.get("event") in ("payment.captured", "order.paid"):
        try:
            entity = event["payload"]["payment"]["entity"]
            order_id = entity.get("order_id")
            payment_id = entity.get("id")
        except (KeyError, TypeError):
            order_id = payment_id = None
        if order_id:
            payment = (await db.execute(
                select(Payment).where(Payment.razorpay_order_id == order_id)
            )).scalar_one_or_none()
            if payment is not None:
                await _activate_paid_plan(db, payment, payment_id)
                logger.info(f"Webhook confirmed payment for order {order_id}; plan -> {payment.plan_key}")

    return api_response(success=True, message="ok")
