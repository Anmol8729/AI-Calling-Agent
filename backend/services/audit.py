"""Audit trail for security-relevant actions.

Design rules
------------
1. **Never break the caller.** An audit write that fails must not fail the action
   the user asked for. Every helper swallows its own errors and logs them.
2. **Its own session.** Audit rows are written on a separate session so they are
   not lost when the caller's transaction rolls back — a *failed* action is often
   the one worth recording.
3. **No secrets.** `detail` is free-form; passwords, tokens and API keys must never
   be put in it. There is a filter below as a backstop.
4. **Append-only.** Nothing here updates or deletes rows.
"""

import logging
from typing import Any, Optional

from backend.models import AuditLog
from backend.services.db import get_sessionmaker

logger = logging.getLogger("audit")

# Stable action verbs. Kept as constants so a typo cannot silently create a second
# spelling that then never shows up in a filtered view.
AUTH_LOGIN = "auth.login"
AUTH_LOGIN_FAILED = "auth.login_failed"
AUTH_LOCKED = "auth.account_locked"
AUTH_LOGOUT_ALL = "auth.logout_all_devices"
AUTH_REGISTER = "auth.register"
AUTH_PASSWORD_CHANGED = "auth.password_changed"
AUTH_PASSWORD_RESET = "auth.password_reset"
AUTH_PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"

NUMBER_CONNECTED = "number.connected"
NUMBER_PROVISIONED = "number.provisioned"
NUMBER_REMOVED = "number.removed"
NUMBER_UPDATED = "number.updated"

ADMIN_PLAN_CHANGED = "admin.plan_changed"
ADMIN_UPGRADE_REVIEWED = "admin.upgrade_request_reviewed"

BILLING_CHECKOUT = "billing.checkout_created"
BILLING_PAYMENT_VERIFIED = "billing.payment_verified"
BILLING_PAYMENT_FAILED = "billing.payment_failed"

SETTINGS_UPDATED = "settings.updated"

# Substrings that must never appear as a detail KEY. A backstop for the "no
# secrets" rule, not a licence to be careless at call sites.
_SENSITIVE_HINTS = ("password", "token", "secret", "authorization", "api_key", "apikey")


def _scrub(detail: Optional[dict]) -> dict:
    """Drop anything whose key looks like a credential."""
    if not detail:
        return {}
    out = {}
    for key, value in detail.items():
        if any(hint in str(key).lower() for hint in _SENSITIVE_HINTS):
            out[str(key)] = "[redacted]"
        else:
            out[str(key)] = value
    return out


def request_context(request) -> dict:
    """Pull client IP and user agent off a FastAPI/Starlette request.

    Prefers `X-Forwarded-For`'s first hop, since the app runs behind a proxy in
    production and `request.client.host` would otherwise be the proxy itself.
    """
    if request is None:
        return {}
    try:
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        ip = forwarded or (request.client.host if request.client else None)
        return {
            "ip_address": (ip or "")[:64] or None,
            "user_agent": (request.headers.get("user-agent") or "")[:255] or None,
        }
    except Exception:  # noqa: BLE001
        return {}


async def record(
    action: str,
    *,
    actor: Optional[dict] = None,
    clinic_id: Any = None,
    target_type: Optional[str] = None,
    target_id: Any = None,
    detail: Optional[dict] = None,
    outcome: str = "success",
    request=None,
    actor_email: Optional[str] = None,
) -> None:
    """Write one audit row. Never raises.

    `actor` is the `current_user` dict when there is a signed-in user; `actor_email`
    covers events where there is not (a failed login, a password reset by token).
    """
    Session = get_sessionmaker()
    if Session is None:
        return

    ctx = request_context(request)
    try:
        # Its own session: a rollback in the caller's transaction must not take the
        # audit row with it, because failed actions are worth recording.
        async with Session() as session:
            session.add(AuditLog(
                actor_user_id=(actor or {}).get("id") or None,
                actor_email=(actor or {}).get("email") or actor_email,
                actor_role=(actor or {}).get("role"),
                clinic_id=clinic_id or (actor or {}).get("clinic_id") or None,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                detail=_scrub(detail),
                outcome=outcome,
                ip_address=ctx.get("ip_address"),
                user_agent=ctx.get("user_agent"),
            ))
            await session.commit()
    except Exception as e:  # noqa: BLE001 — auditing must never break the request
        logger.error(f"Failed to write audit row for {action!r}: {e}")


async def list_for_clinic(clinic_id, limit: int = 100, offset: int = 0) -> list:
    """Most recent entries for one tenant, newest first."""
    from sqlalchemy import select, desc

    from backend.utils.helpers import serialize_models, to_uuid

    Session = get_sessionmaker()
    cid = to_uuid(clinic_id)
    if Session is None or cid is None:
        return []
    async with Session() as session:
        rows = (await session.execute(
            select(AuditLog)
            .where(AuditLog.clinic_id == cid)
            .order_by(desc(AuditLog.created_at))
            .limit(max(min(int(limit), 200), 1))
            .offset(max(int(offset), 0))
        )).scalars().all()
    return serialize_models(rows)
