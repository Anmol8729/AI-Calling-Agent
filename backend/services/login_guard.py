"""Per-account brute-force lockout for the login endpoint.

The IP rate limit on `/api/auth/login` is cheap flood protection, not a
credential-stuffing control: an attacker with a pool of addresses (or a botnet, or
just a mobile network re-issuing IPs) never trips it. This tracks failures against
the ACCOUNT instead, so guessing one user's password gets progressively slower no
matter where the attempts come from.

State lives in `users` rather than Redis deliberately — a lockout must survive a
restart and must not evaporate because a cache was flushed.

Design notes
------------
* **Escalating, not permanent.** A permanent lock is a denial-of-service against
  the real owner: anyone who knows an email could lock them out forever. The delay
  grows instead, which makes online guessing impractical while the legitimate user
  is only ever locked out for minutes.
* **Failures are counted for real accounts only**, but the *response* is identical
  whether or not the address exists, so this never becomes an account-enumeration
  oracle.
* **The bcrypt comparison still runs** for a locked account before rejecting, so a
  locked account and a wrong password take a similar amount of time. Skipping the
  hash would leak lock state through response timing.
"""

import logging
from datetime import datetime, timedelta

from backend.config.settings import settings

logger = logging.getLogger("login-guard")


def _threshold() -> int:
    return max(int(getattr(settings, "LOGIN_MAX_ATTEMPTS", 5) or 5), 3)


def _base_lock_minutes() -> int:
    return max(int(getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15) or 15), 1)


def lockout_for(attempts: int) -> timedelta:
    """Escalating delay once the threshold is crossed.

    With the defaults (5 attempts, 15 minutes) that is 15m, 30m, 60m, then capped
    at 120m. Roughly a dozen guesses a day — useless for an attacker, tolerable for
    someone who genuinely forgot which password they used.
    """
    over = max(attempts - _threshold(), 0)
    minutes = min(_base_lock_minutes() * (2 ** over), 120)
    return timedelta(minutes=minutes)


def is_locked(user) -> bool:
    locked_until = getattr(user, "locked_until", None)
    return bool(locked_until and locked_until > datetime.utcnow())


def lock_remaining_minutes(user) -> int:
    locked_until = getattr(user, "locked_until", None)
    if not locked_until:
        return 0
    remaining = (locked_until - datetime.utcnow()).total_seconds() / 60
    return max(int(remaining + 0.999), 1)


def register_failure(user) -> bool:
    """Record a failed attempt. Returns True if the account is now locked.

    Caller is responsible for committing the session.
    """
    attempts = int(getattr(user, "failed_login_attempts", 0) or 0) + 1
    user.failed_login_attempts = attempts
    if attempts >= _threshold():
        user.locked_until = datetime.utcnow() + lockout_for(attempts)
        logger.warning(
            f"Account {user.email} locked after {attempts} failed attempts "
            f"until {user.locked_until} UTC."
        )
        return True
    return False


def register_success(user) -> None:
    """Clear the counters after a genuine sign-in. Caller commits."""
    if int(getattr(user, "failed_login_attempts", 0) or 0) or getattr(user, "locked_until", None):
        logger.info(f"Resetting failed-login counter for {user.email} after a successful sign-in.")
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.utcnow()
