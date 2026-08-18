"""
Meta WhatsApp Cloud API sender (official, no BSP).

Proactive appointment messages are business-initiated, so they must use
pre-approved template messages. Each template here expects 3 body parameters in
order: {{1}} customer name, {{2}} business name, {{3}} when (date/time string).

Everything is best-effort: sends never raise, and the whole feature is a no-op
until WHATSAPP_ACCESS_TOKEN + WHATSAPP_PHONE_NUMBER_ID are configured.
Only the access token is used server-side; nothing WhatsApp-related reaches the
browser.
"""

import logging
import re

import httpx

from backend.config.settings import settings

logger = logging.getLogger("whatsapp")


def _normalize(phone: str):
    """Return digits-only international number (E.164 without '+'), or None."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return None
    # A bare 10-digit number is treated as local and gets the default country code.
    if len(digits) == 10:
        digits = f"{settings.WHATSAPP_DEFAULT_COUNTRY_CODE}{digits}"
    return digits


def resolve_config(tenant):
    """Effective WhatsApp config for a tenant (dict), or None if not sendable.

    Per-tenant values (their own WhatsApp number) override the platform .env
    defaults. Returns None when neither the tenant nor the platform has both an
    access token and a phone number id configured.
    """
    t = tenant or {}
    token = (t.get("whatsapp_access_token") or "").strip() or settings.WHATSAPP_ACCESS_TOKEN
    phone_id = (t.get("whatsapp_phone_number_id") or "").strip() or settings.WHATSAPP_PHONE_NUMBER_ID
    if not (token and phone_id):
        return None
    return {
        "access_token": token,
        "phone_number_id": phone_id,
        "api_version": settings.WHATSAPP_API_VERSION,
        "lang": (t.get("whatsapp_template_lang") or "").strip() or settings.WHATSAPP_TEMPLATE_LANG,
        "confirm_template": (t.get("whatsapp_confirm_template") or "").strip() or settings.WHATSAPP_CONFIRM_TEMPLATE,
        "reminder_template": (t.get("whatsapp_reminder_template") or "").strip() or settings.WHATSAPP_REMINDER_TEMPLATE,
    }


async def send_template(config: dict, to_phone: str, template_name: str, params) -> bool:
    if not config or not config.get("access_token") or not config.get("phone_number_id"):
        return False
    to = _normalize(to_phone)
    if not to or not template_name:
        return False

    url = f"https://graph.facebook.com/{config['api_version']}/{config['phone_number_id']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": config.get("lang") or settings.WHATSAPP_TEMPLATE_LANG},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}
            ],
        },
    }
    headers = {
        "Authorization": f"Bearer {config['access_token']}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                logger.warning(f"WhatsApp send failed {resp.status_code}: {resp.text}")
                return False
            return True
    except Exception as e:
        logger.warning(f"WhatsApp send error: {e}")
        return False


async def verify_credentials(phone_number_id: str, access_token: str):
    """Check a phone number ID + access token pair against the Cloud API.

    Returns ``(ok, error_message, info)``. ``info`` carries the number Meta has on
    file (``display_phone_number``, ``verified_name``) so the dashboard can show
    WHICH number it just connected instead of only a green tick.

    Reads the phone number object rather than sending anything: a send would need an
    approved template and a real recipient, and would cost the tenant a message just
    to test a credential. A GET is free and fails for exactly the two reasons worth
    telling the user apart — a bad token and a bad/invisible phone number ID.

    Never raises, and never logs the token. Only the id is safe to log.
    """
    phone_number_id = (phone_number_id or "").strip()
    access_token = (access_token or "").strip()
    if not phone_number_id:
        return False, "Enter your WhatsApp Business Phone Number ID.", None
    if not access_token:
        return False, "Enter your WhatsApp Cloud API access token.", None

    url = f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/{phone_number_id}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                params={"fields": "display_phone_number,verified_name,quality_rating"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.TimeoutException:
        return False, "WhatsApp did not respond in time. Try again in a moment.", None
    except Exception as e:
        logger.warning(f"WhatsApp verify error for id={phone_number_id}: {type(e).__name__}")
        return False, "Could not reach WhatsApp. Check your connection and try again.", None

    if resp.status_code == 200:
        data = resp.json() if resp.content else {}
        logger.info(f"WhatsApp credentials verified for id={phone_number_id}")
        return True, None, {
            "display_phone_number": data.get("display_phone_number"),
            "verified_name": data.get("verified_name"),
            "quality_rating": data.get("quality_rating"),
        }

    # Meta replies {"error": {"message": ..., "code": ..., "type": ...}}.
    detail = ""
    try:
        detail = ((resp.json() or {}).get("error") or {}).get("message") or ""
    except Exception:
        detail = ""
    detail = detail.strip()[:300]

    # Status alone cannot separate the two causes: Meta answers 404 both for a
    # phone number id that does not exist AND for one this token cannot see.
    if resp.status_code in (401, 403):
        message = "WhatsApp rejected the access token. Generate a new permanent token and paste it again."
    elif resp.status_code == 404:
        message = "WhatsApp could not find that Phone Number ID with this token. Check both values."
    elif resp.status_code == 429:
        message = "WhatsApp is rate limiting this app. Wait a minute and try again."
    else:
        message = "WhatsApp rejected these credentials."
    if detail:
        message = f"{message} Meta said: {detail}"

    logger.warning(f"WhatsApp verify failed {resp.status_code} for id={phone_number_id}")
    return False, message, None


async def send_appointment_confirmation(config: dict, to_phone: str, name: str, business: str, when: str) -> bool:
    return await send_template(
        config, to_phone, (config or {}).get("confirm_template"),
        [name or "there", business or "us", when or ""],
    )


async def send_appointment_reminder(config: dict, to_phone: str, name: str, business: str, when: str) -> bool:
    return await send_template(
        config, to_phone, (config or {}).get("reminder_template"),
        [name or "there", business or "us", when or ""],
    )
