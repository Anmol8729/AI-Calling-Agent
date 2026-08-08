import logging
import smtplib
import ssl
from email.message import EmailMessage

from backend.config.settings import settings

logger = logging.getLogger("email-service")

# Port 465 is SMTPS: TLS is established before any SMTP command. Ports 587/25 are
# plaintext connections that are then upgraded with STARTTLS. Getting this backwards
# is the classic SMTP misconfiguration — calling starttls() on 465 fails with an
# opaque error, and the operator sees only "failed to send".
IMPLICIT_TLS_PORT = 465


def describe_config() -> str:
    """One line describing how mail will be sent. Never includes the password."""
    if not settings.SMTP_HOST:
        return "SMTP not configured — emails are written to the log instead of sent"
    mode = "implicit TLS (SMTPS)" if settings.SMTP_PORT == IMPLICIT_TLS_PORT else (
        "STARTTLS" if settings.SMTP_TLS else "no encryption"
    )
    sender = settings.SMTP_FROM or settings.SMTP_USER or "no-reply@clarivo.ai"
    auth = f"as {settings.SMTP_USER}" if settings.SMTP_USER else "no auth"
    return f"SMTP {settings.SMTP_HOST}:{settings.SMTP_PORT} ({mode}), {auth}, From={sender}"


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
        # Most providers reject or spam-file a From address on a domain they have not
        # verified for this account, so SMTP_FROM should be set. The fallback exists
        # only so development does not crash; check_production_config warns about it.
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER or "no-reply@clarivo.ai"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if settings.SMTP_PORT == IMPLICIT_TLS_PORT:
            # SMTPS: wrap the socket in TLS from the start. STARTTLS here would fail.
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT, timeout=15, context=context
            ) as server:
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                if settings.SMTP_TLS:
                    server.starttls(context=ssl.create_default_context())
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        # Deliberately broad: a mail failure must never break the request that
        # triggered it. The caller decides what the user sees (password reset, for
        # example, reports success either way to avoid leaking which emails exist).
        logger.error(f"Failed to send email to {to}: {e} [{describe_config()}]")
        return False


if __name__ == "__main__":
    # Operator tool: prove SMTP works without waiting for a real user to click
    # "forgot password". Without this the first test of the mail path is a customer
    # failing to reset their password, and the only symptom is a log line.
    #
    #   python -m backend.services.email you@example.com
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(describe_config())

    recipient = sys.argv[1] if len(sys.argv) > 1 else ""
    if not recipient:
        print("\nUsage: python -m backend.services.email <recipient@example.com>")
        raise SystemExit(2)
    if not settings.SMTP_HOST:
        print("\nSMTP_HOST is empty, so nothing would be sent. Set it in .env first.")
        raise SystemExit(1)

    ok = send_email(
        recipient,
        "Clarivo SMTP test",
        "If you are reading this, Clarivo can send email.\n\n"
        "Password resets and email verification will work.",
    )
    print(f"\nsent: {ok}")
    raise SystemExit(0 if ok else 1)
