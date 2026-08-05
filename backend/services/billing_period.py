"""Where a billing month starts and ends.

The bug this replaces
---------------------
Three separate places computed the month boundary as
`datetime(utcnow().year, utcnow().month, 1)` — midnight UTC on the 1st. The
business runs in India (UTC+5:30) and `call_logs.created_at` is stored as naive UTC,
so for the first 5 hours 30 minutes of every month, calls made **that morning IST**
were counted against the **previous** month. Concretely, a call at 02:00 IST on the
1st fell before 00:00 UTC on the 1st, so:

  * it was billed to the month that had already closed;
  * it counted against a quota the customer had already used up, which could reject
    a call they were entitled to;
  * the usage figure on the dashboard disagreed with the invoice.

Small window, but it recurs every month and it is money.

The logic also lived in three copies (`billing.py`, `admin.py`, and the quota check
in `repository.py`), so they could drift apart. One helper now, used everywhere.

Naive UTC is kept as the storage convention — changing every column to be
timezone-aware is a much larger migration (tracked as M4). This converts at the
boundary instead, which fixes the arithmetic without touching the schema.
"""

import logging
from datetime import datetime, timedelta, timezone

from backend.config.settings import settings

logger = logging.getLogger("billing-period")

# Default matches where the business and its customers are. UTC+5:30.
_DEFAULT_OFFSET_MINUTES = 330


def _offset() -> timedelta:
    """The billing timezone's offset from UTC.

    A fixed offset rather than a named zone on purpose: India has no daylight
    saving, so an offset is exact and avoids a tzdata dependency. Set
    BILLING_UTC_OFFSET_MINUTES for a business elsewhere (e.g. 0 for UTC, -300 for
    US Eastern standard time).
    """
    raw = getattr(settings, "BILLING_UTC_OFFSET_MINUTES", _DEFAULT_OFFSET_MINUTES)
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            f"BILLING_UTC_OFFSET_MINUTES={raw!r} is not a number; using "
            f"{_DEFAULT_OFFSET_MINUTES} (IST)."
        )
        minutes = _DEFAULT_OFFSET_MINUTES
    # Guard against a typo silently shifting every invoice.
    if not -840 <= minutes <= 840:
        logger.error(
            f"BILLING_UTC_OFFSET_MINUTES={minutes} is outside +/-14h; using "
            f"{_DEFAULT_OFFSET_MINUTES} (IST)."
        )
        minutes = _DEFAULT_OFFSET_MINUTES
    return timedelta(minutes=minutes)


def local_now() -> datetime:
    """Current wall-clock time in the billing timezone, naive."""
    return datetime.now(timezone.utc).replace(tzinfo=None) + _offset()


def month_start_utc(reference: datetime | None = None) -> datetime:
    """Naive-UTC instant at which the current billing month began.

    Comparable directly against `created_at`, which is stored as naive UTC.
    """
    local = (reference + _offset()) if reference is not None else local_now()
    local_first = datetime(local.year, local.month, 1)
    return local_first - _offset()


def next_month_start_utc(reference: datetime | None = None) -> datetime:
    """Naive-UTC instant at which the current billing month ends."""
    local = (reference + _offset()) if reference is not None else local_now()
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1) - _offset()


def month_label(reference: datetime | None = None) -> str:
    """Human label for the current billing month, e.g. "August 2026"."""
    local = (reference + _offset()) if reference is not None else local_now()
    return local.strftime("%B %Y")
