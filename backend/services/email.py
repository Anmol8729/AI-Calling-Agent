import logging
import smtplib
from email.message import EmailMessage

from backend.config.settings import settings

logger = logging.getLogger("email-service")


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP.

    If SMTP is not configured (SMTP_HOST empty), the message — including any link —
    is logged server-side so development flows still work. Returns True only if an
    email was actually sent. This function is synchronous; call it from async code
    via `await asyncio.to_thread(send_email, ...)` so it doesn't block the loop.
    """
    if not settings.SMTP_HOST:
        logger.info(f"[EMAIL not configured] To={to} | Subject={subject}\n{body}")
        return False
    try:
        msg = EmailMessage()
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER or "no-reply@clarivo.ai"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            if settings.SMTP_TLS:
                server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False
