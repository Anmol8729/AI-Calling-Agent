"""Closes call_logs rows that were left stuck at status="active".

Why this is needed
------------------
The voice agent reports the end of a call on a best-effort background task. That
report can simply never arrive:

  * on Windows, LiveKit's native layer panics during call teardown
    (`malformed serialized RtcError`) and kills the worker process first — this was
    observed on a real verification call, which stayed `active` with `duration: 0`;
  * the agent process can be killed, lose network, or be redeployed mid-call.

Without a sweeper those rows stay `active` forever: the dashboard's live view shows
calls that never end, the funnel counts them as in-progress, and average duration is
dragged toward zero. Running the agent on Linux removes the main trigger, but the
data still needs a backstop — a crashed agent must not corrupt a customer's stats.

Deliberately conservative: duration is derived from the last transcript turn, not
from "now", so a row swept late does not invent a long call.
"""

import logging

from backend.config.settings import settings
from backend.services import repository
from backend.services.job_lock import run_as_single_owner

logger = logging.getLogger("call-sweeper")


async def sweep_once() -> int:
    """One pass. Returns the number of calls closed."""
    return await repository.close_stale_calls(settings.CALL_STALE_AFTER_MIN)


async def call_sweeper_loop():
    """Periodic sweep, on ONE process only.

    Every replica starts this loop, but the advisory lock means only one actually
    sweeps. Duplicated sweeps here would be wasteful rather than harmful, but using
    the same mechanism as the reminder worker keeps the two consistent — and if the
    owner dies, another replica takes over.
    """
    interval = max(int(settings.CALL_SWEEP_INTERVAL_SEC), 30)
    logger.info(
        f"Call sweeper starting (every {interval}s, closes 'active' calls older "
        f"than {settings.CALL_STALE_AFTER_MIN}m)."
    )
    await run_as_single_owner("call_sweeper", sweep_once, interval=interval)
