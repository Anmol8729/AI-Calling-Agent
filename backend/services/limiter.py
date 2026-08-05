"""Shared request rate limiter.

Storage matters here. The default is in-process memory, which has two failures
that make it close to useless as a brute-force control in production:

  * **Per-process.** Two uvicorn workers (or two replicas behind a load balancer)
    each keep their own counters, so a "10/minute" limit is really 10 per minute
    *per process*. Scaling out silently weakens it.
  * **Lost on restart.** An attacker who trips the limit only has to wait for the
    next deploy, and deploys are frequent.

So when `REDIS_URL` is set and actually reachable, counters live in Redis and are
shared by every process. If Redis is unreachable we fall back to memory and log
loudly rather than refusing to boot — an unreachable cache should not take the
whole API down, but the operator needs to know the limits just got weaker.

Note this is still IP-keyed, which is the right shape for cheap flood protection
but not for credential stuffing: an attacker with a pool of IPs slips straight
through. Per-ACCOUNT lockout lives in `backend/services/login_guard.py` and is
backed by the database, so it survives restarts and does not care about IPs.
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config.settings import settings

logger = logging.getLogger("limiter")


def _storage_uri() -> str | None:
    """Return a working Redis URI, or None to fall back to in-memory counters."""
    uri = (settings.REDIS_URL or "").strip()
    if not uri:
        logger.warning(
            "REDIS_URL is not set — rate limits are per-process and reset on restart. "
            "Set it (and run the compose redis service) before serving real traffic."
        )
        return None
    try:
        # limits' storage layer is what slowapi uses under the hood; probing it here
        # means a bad URI surfaces at boot instead of on the first limited request.
        from limits.storage import storage_from_string

        storage = storage_from_string(uri)
        if not storage.check():
            raise RuntimeError("storage health check returned false")
        logger.info("Rate limiter using Redis storage (shared across processes).")
        return uri
    except Exception as e:  # noqa: BLE001 — degrade, don't fail the boot
        logger.error(
            f"Redis at REDIS_URL is unreachable ({e}). Falling back to in-memory rate "
            "limits: they are per-process and reset on restart, so brute-force "
            "protection is weaker until Redis is available."
        )
        return None


_uri = _storage_uri()

# Imported by app.py (wiring) and by routes that apply @limiter.limit(...).
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_uri,
    # Without this a single blocked request can raise inside the limiter and 500;
    # a limiter failure should never take an endpoint down.
    swallow_errors=True,
)

# True when limits are shared across processes. Surfaced by /api/admin/diagnostics
# so an operator can see at a glance whether protection is degraded.
LIMITER_SHARED = _uri is not None
