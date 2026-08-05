"""Security response headers + startup configuration guards.

FastAPI ships no equivalent of Helmet, so before this the API returned no
security headers at all: no HSTS, no clickjacking protection, no MIME-sniffing
protection, and a permissive referrer policy.
"""

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.config.settings import settings

logger = logging.getLogger("security")

# The value shipped as the JWT_SECRET default. A deployment left on this can have
# its session tokens forged by anyone who has read the source.
INSECURE_JWT_DEFAULT = "super-secret-receptionist-key-change-this-in-production"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardening headers to every response.

    CSP is intentionally strict but allows Razorpay Checkout, which is loaded as a
    third-party script on the billing page. It applies to API responses only —
    the dashboard is served by its own host (Vite/CDN), which should send its own.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool = True) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'; connect-src 'self' https://api.razorpay.com",
        )
        # Only meaningful over TLS, and sending it in local dev would pin
        # http://localhost to https for the developer's whole browser profile.
        if self._hsts:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        # Never let a proxy or browser cache an authenticated API response.
        if request.url.path.startswith("/api/"):
            headers.setdefault("Cache-Control", "no-store")
        return response


def check_production_config() -> list[str]:
    """Return a list of fatal misconfigurations for a production deployment.

    Called at startup. In production these must stop the process: booting with a
    known JWT secret or a wildcard CORS origin is worse than failing to boot,
    because it looks healthy while being trivially exploitable.
    """
    problems: list[str] = []

    if not settings.JWT_SECRET or settings.JWT_SECRET == INSECURE_JWT_DEFAULT:
        problems.append(
            "JWT_SECRET is unset or still the built-in default — anyone can forge "
            "session tokens. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    elif len(settings.JWT_SECRET) < 32:
        problems.append(
            f"JWT_SECRET is only {len(settings.JWT_SECRET)} characters; use at least 32."
        )

    origins = [o.strip() for o in (settings.CORS_ORIGINS or "").split(",") if o.strip()]
    if "*" in origins:
        problems.append(
            "CORS_ORIGINS contains '*', which is invalid with allow_credentials=True. "
            "List the exact dashboard origin(s)."
        )
    if not origins:
        problems.append("CORS_ORIGINS is empty — the dashboard will be blocked by CORS.")
    localhost = [o for o in origins if "localhost" in o or "127.0.0.1" in o]
    if localhost:
        problems.append(
            f"CORS_ORIGINS still allows local origins {localhost} — remove them in production."
        )

    if not settings.AGENT_INTERNAL_SECRET:
        problems.append(
            "AGENT_INTERNAL_SECRET is unset, so the voice agent's internal endpoints "
            "fall back to authenticating with JWT_SECRET. That reuses the token-signing "
            "key as an API credential: if it leaks, an attacker can mint tokens for any "
            "user. Set a separate value."
        )
    elif settings.AGENT_INTERNAL_SECRET == settings.JWT_SECRET:
        problems.append(
            "AGENT_INTERNAL_SECRET must not be the same value as JWT_SECRET."
        )

    # Checked after connect_to_db() has run, so this reflects the real connection.
    try:
        from backend.services import db as _db

        if not _db.DB_TLS_VERIFIED:
            problems.append(
                "The database connection is encrypted but NOT verified — the "
                "database's identity is unchecked, so an interceptor could read or "
                "rewrite every query. Restore backend/certs/"
                "supabase-prod-ca-2021.crt or set DB_SSL_ROOT_CERT."
            )
    except Exception:  # noqa: BLE001 — never let a check break the boot
        pass

    try:
        from backend.services.limiter import LIMITER_SHARED

        if not LIMITER_SHARED:
            problems.append(
                "Rate limits are stored in process memory: they are per-worker and "
                "reset on every restart, so brute-force protection is weak. Set "
                "REDIS_URL to a reachable Redis."
            )
    except Exception:  # noqa: BLE001
        pass

    if settings.DB_AUTO_SCHEMA:
        problems.append(
            "DB_AUTO_SCHEMA is on, so the app rewrites the schema at every boot. "
            "That has no version history, no rollback path, and races when several "
            "replicas start together. Set DB_AUTO_SCHEMA=false and run "
            "`alembic upgrade head` as a deploy step."
        )

    if not (settings.SMTP_HOST or "").strip():
        problems.append(
            "SMTP is not configured, so no email can be delivered: password resets "
            "and email verification silently do nothing (the link is only written to "
            "the server log). Platform super-admin is granted by an email allowlist, "
            "so without verification whoever registers an allowlisted address first "
            "gains full access to every tenant. Set SMTP_HOST and friends."
        )

    if not (settings.APP_BASE_URL or "").startswith("https://"):
        problems.append(
            f"APP_BASE_URL ({settings.APP_BASE_URL!r}) is not https — password-reset "
            "links sent to users would be insecure."
        )

    return problems


def enforce_production_config() -> None:
    """Log every config problem; abort the boot when ENV is production."""
    problems = check_production_config()
    if not problems:
        logger.info("Production config check passed.")
        return

    is_prod = (settings.ENV or "").strip().lower() in ("production", "prod")
    for p in problems:
        (logger.critical if is_prod else logger.warning)(f"CONFIG: {p}")
    if is_prod:
        raise RuntimeError(
            f"Refusing to start in production with {len(problems)} insecure "
            "configuration value(s); see the CONFIG entries logged above."
        )
    logger.warning(
        "ENV is not 'production', so the above are warnings only. They WILL block "
        "startup once ENV=production."
    )


def generate_secret() -> str:
    """Helper for operators: a fresh high-entropy secret."""
    return secrets.token_urlsafe(48)
