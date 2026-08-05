"""Makes a background job run on exactly ONE process, however many are running.

The problem
-----------
The reminder worker and the call sweeper start in the app lifespan, so every replica
(and every uvicorn worker) starts its own copy. For the sweeper that is merely
wasteful. For the reminder worker it is a customer-visible defect: two replicas both
read the same appointment with `reminder_sent = False` and both send, so the patient
gets the same WhatsApp message twice — the flag is only written after sending.

Why a lease table and NOT a Postgres advisory lock
--------------------------------------------------
Advisory locks were the first choice and they are WRONG for this deployment. This
database is reached through Supabase's pooler (Supavisor). Measured against the live
database:

  * Three separate sessions opened from one process all landed on the **same**
    backend pid — so two "different replicas" can share a backend and both believe
    they hold the lock.
  * Locks taken by a process that then exited were still held, `state=idle`, on a
    pooled backend afterwards. Advisory locks are released when the *backend*
    session ends, and the pooler deliberately keeps backends alive. So the lock
    leaks and the job wedges permanently — exactly the failure advisory locks were
    supposed to prevent.

A lease row avoids both: it is ordinary data written in a transaction, so pooling is
irrelevant, and it expires on its own if the owner dies. Acquire and renew are a
single atomic statement, so there is no check-then-take race.
"""

import asyncio
import logging
import os
import socket
import uuid

from sqlalchemy import text

from backend.services.db import get_sessionmaker

logger = logging.getLogger("job-lock")

# Identifies this process in the lease row. Host + pid makes a stuck lease
# traceable to a machine; the random suffix keeps it unique if a pid is reused.
OWNER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

# How long a lease stays valid without a renewal, and therefore the worst-case
# delay before another replica picks up a job whose owner crashed.
#
# It does NOT need to exceed the job's work interval, because renewal runs on its
# own heartbeat (see _heartbeat). That separation matters: the real intervals are
# 300s, so tying the TTL to them would mean a crashed owner stalled the job for at
# least five minutes.
LEASE_TTL_SECONDS = 90

# How often a process that does not hold the lease re-checks.
STANDBY_RETRY_SECONDS = 30

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS job_leases (
    name        varchar(64) PRIMARY KEY,
    owner       varchar(128) NOT NULL,
    acquired_at timestamptz  NOT NULL DEFAULT now(),
    renewed_at  timestamptz  NOT NULL DEFAULT now(),
    expires_at  timestamptz  NOT NULL
)
"""

# One statement, so acquiring and renewing cannot race. The UPDATE only fires when
# the existing lease has expired or is already ours; otherwise ON CONFLICT matches
# no row, RETURNING is empty, and we know someone else owns it.
_ACQUIRE_SQL = """
INSERT INTO job_leases (name, owner, acquired_at, renewed_at, expires_at)
VALUES (:name, :owner, now(), now(), now() + make_interval(secs => :ttl))
ON CONFLICT (name) DO UPDATE
    SET owner      = EXCLUDED.owner,
        renewed_at = now(),
        expires_at = now() + make_interval(secs => :ttl),
        acquired_at = CASE
            WHEN job_leases.owner = EXCLUDED.owner THEN job_leases.acquired_at
            ELSE now()
        END
    WHERE job_leases.expires_at < now()
       OR job_leases.owner = EXCLUDED.owner
RETURNING owner, acquired_at
"""

_RELEASE_SQL = "DELETE FROM job_leases WHERE name = :name AND owner = :owner"

_ensured = False


async def _ensure_table() -> bool:
    global _ensured
    if _ensured:
        return True
    Session = get_sessionmaker()
    if Session is None:
        return False
    try:
        async with Session() as session:
            await session.execute(text(_TABLE_DDL))
            await session.commit()
        _ensured = True
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Could not create the job_leases table: {e}")
        return False


async def acquire_or_renew(name: str) -> bool:
    """Take the lease for `name`, or renew it if we already hold it.

    Returns True when this process owns the job for the next LEASE_TTL_SECONDS.
    """
    if not await _ensure_table():
        return False
    Session = get_sessionmaker()
    if Session is None:
        return False
    try:
        async with Session() as session:
            row = (await session.execute(
                text(_ACQUIRE_SQL),
                {"name": name, "owner": OWNER_ID, "ttl": LEASE_TTL_SECONDS},
            )).first()
            await session.commit()
            return row is not None
    except Exception as e:  # noqa: BLE001
        logger.error(f"Lease check failed for {name!r}: {e}")
        return False


async def release(name: str) -> None:
    """Give up the lease so another replica can take over immediately."""
    Session = get_sessionmaker()
    if Session is None:
        return
    try:
        async with Session() as session:
            await session.execute(text(_RELEASE_SQL), {"name": name, "owner": OWNER_ID})
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.error(f"Could not release lease {name!r}: {e}")


async def _heartbeat(name: str, lost: asyncio.Event):
    """Renew the lease on its own schedule and signal if it is ever lost.

    Renewal is deliberately DECOUPLED from the work interval. Renewing only after
    each pass would force the TTL to exceed the interval, and the interval here is
    300s — so a crashed owner would leave the job stalled for at least that long,
    and any pass slower than the TTL would hand ownership to another replica
    mid-run. A short TTL plus frequent renewal gives fast failover *and* a slow
    work interval.
    """
    every = max(LEASE_TTL_SECONDS // 3, 5)
    while True:
        await asyncio.sleep(every)
        if not await acquire_or_renew(name):
            lost.set()
            return


async def run_as_single_owner(name: str, work, *, interval: int):
    """Run `work()` every `interval` seconds, on one process only.

    A process that loses its lease (it stalled long enough to expire, or the
    database was briefly unreachable) stops running the job and drops back to
    standby, rather than continuing alongside whichever replica took over — which
    for the reminder worker would mean customers getting duplicate messages.
    """
    owned = False
    announced_standby = False
    heartbeat = None
    lost = asyncio.Event()

    async def _stop_heartbeat():
        nonlocal heartbeat
        if heartbeat is not None:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            heartbeat = None

    try:
        while True:
            if not owned:
                if not await acquire_or_renew(name):
                    if not announced_standby:
                        logger.info(
                            f"Job {name!r} is owned by another process; standing by "
                            f"(re-checking every {STANDBY_RETRY_SECONDS}s)."
                        )
                        announced_standby = True
                    await asyncio.sleep(STANDBY_RETRY_SECONDS)
                    continue
                logger.info(f"Job {name!r} acquired by {OWNER_ID}.")
                owned = True
                announced_standby = False
                lost = asyncio.Event()
                heartbeat = asyncio.create_task(_heartbeat(name, lost))

            try:
                await work()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — one bad pass must not end the loop
                logger.error(f"Job {name!r} pass failed: {e}")

            # Wait out the interval, but wake immediately if the lease is lost so we
            # stop working rather than racing the new owner.
            try:
                await asyncio.wait_for(lost.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

            logger.warning(
                f"Job {name!r} lease lost — another process has taken over. Standing by."
            )
            owned = False
            await _stop_heartbeat()
    except asyncio.CancelledError:
        logger.info(f"Job {name!r} stopping.")
        raise
    finally:
        await _stop_heartbeat()
        if owned:
            # Release explicitly so a rolling deploy hands over at once instead of
            # leaving the job idle until the lease expires.
            await release(name)
