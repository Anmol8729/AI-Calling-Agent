"""
Async Postgres (Supabase) data layer.

Replaces the previous MongoDB (motor) connection. We treat Supabase purely as
hosted Postgres and talk to it with SQLAlchemy 2.0 async + asyncpg.

Connection config is built so it works with Supabase's transaction pooler
(pgbouncer), which does not support cached/named prepared statements:
  - statement_cache_size=0            -> disables asyncpg's prepared-statement cache
  - prepared_statement_cache_size=0   -> disables SQLAlchemy's asyncpg PS cache
  - prepared_statement_name_func      -> unique name per statement
See: https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT

The URL is assembled with SQLAlchemy's URL.create() from individual parts
(DB_USER/DB_PASSWORD/DB_HOST/...) so passwords with special characters (@, #,
:, /) need no URL-encoding. A full DATABASE_URL is also supported and takes
precedence.
"""

import hashlib
import logging
import ssl
import uuid
from pathlib import Path
from urllib.parse import urlsplit, unquote

from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from backend.config.settings import settings
from backend.models import Base

logger = logging.getLogger("db-service")

# Set during connect_to_db(); stay None until a successful connection so the app
# can still boot (and surface a clear 503) when the DB isn't configured.
engine = None
AsyncSessionLocal = None

# Additive, idempotent column migrations applied on startup (create_all only
# creates missing tables, it never ALTERs existing ones). Keep each statement
# safe to run repeatedly.
_COLUMN_MIGRATIONS = [
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS industry varchar(50)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS monthly_call_limit integer",
    # Per-tenant cap on claimable phone numbers. A spend control: each DID is
    # ~₹100 setup + ₹500/month, and provisioning was previously unlimited for
    # every plan including the free trial.
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS number_limit integer",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS notify_email varchar(255)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS whatsapp_phone_number_id varchar(64)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS whatsapp_access_token text",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS whatsapp_template_lang varchar(20)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS whatsapp_confirm_template varchar(100)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS whatsapp_reminder_template varchar(100)",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appointment_at timestamp",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS duration_min integer NOT NULL DEFAULT 30",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS phone varchar(50)",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_sent boolean NOT NULL DEFAULT false",
    # Token/queue appointment mode (per-tenant booking_mode + daily "now serving").
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS booking_mode varchar(20) NOT NULL DEFAULT 'time'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS queue_current_number integer NOT NULL DEFAULT 0",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS queue_current_date varchar(10)",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS token_number integer",
    "ALTER TABLE appointments ADD COLUMN IF NOT EXISTS token_date varchar(10)",
    # Session control on users. Without these there is no way to revoke a JWT:
    # logout was browser-only and a stolen token survived a password reset.
    # `token_version` is carried in each token as `ver` and compared per request,
    # so bumping it kills every existing session for that user.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version integer NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at timestamp",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true",
    # Per-account brute-force lockout. In the DB, not the rate limiter, because an
    # IP-keyed limit does nothing against credential stuffing from many IPs and is
    # lost on every restart.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts integer NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until timestamp",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at timestamp",
    # Mailbox ownership. Critical because super-admin is granted by an email
    # allowlist, so without this whoever registers an allowlisted address first
    # became platform admin with no proof at all.
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at timestamp",
    # Dashboard reads are always "this tenant, newest first" / "this tenant in this
    # month". Single-column indexes on clinic_id made Postgres sort or filter the
    # whole tenant slice; these composites serve those queries directly.
    # Last transcript turn, so a call whose "ended" report never arrived can still
    # be closed with a real duration (see backend/jobs/call_sweeper.py).
    "ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS last_activity_at timestamp",
    # Audit trail reads are always "this tenant, newest first".
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_clinic_created ON audit_logs (clinic_id, created_at DESC)",
    # Single-owner election for background jobs. A LEASE ROW, not a Postgres
    # advisory lock: this database is behind Supabase's pooler, where separate
    # sessions can share a backend and a lock survives the process that took it —
    # measured directly, so an advisory lock would leak and wedge the job forever.
    # See backend/services/job_lock.py.
    """CREATE TABLE IF NOT EXISTS job_leases (
        name        varchar(64) PRIMARY KEY,
        owner       varchar(128) NOT NULL,
        acquired_at timestamptz  NOT NULL DEFAULT now(),
        renewed_at  timestamptz  NOT NULL DEFAULT now(),
        expires_at  timestamptz  NOT NULL
    )""",
    # Partial index: the sweeper only ever scans rows still marked active, which is
    # a tiny slice of the table.
    "CREATE INDEX IF NOT EXISTS ix_call_logs_active ON call_logs (created_at) WHERE status = 'active'",
    "CREATE INDEX IF NOT EXISTS ix_call_logs_clinic_created ON call_logs (clinic_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_appointments_clinic_at ON appointments (clinic_id, appointment_at)",
]


def get_sessionmaker():
    """Return the async sessionmaker, or None if the DB isn't connected yet."""
    return AsyncSessionLocal


def _build_url():
    """Build a SQLAlchemy URL for asyncpg, or return None if unconfigured.

    Priority: a full DATABASE_URL (if set) is parsed into parts; otherwise the
    individual DB_* settings are used. Either way URL.create() handles escaping,
    so special characters in the password are safe and need no encoding.
    """
    raw = (settings.DATABASE_URL or "").strip()
    if raw:
        parts = urlsplit(raw)
        return URL.create(
            "postgresql+asyncpg",
            username=unquote(parts.username) if parts.username else None,
            password=unquote(parts.password) if parts.password else None,
            host=parts.hostname,
            port=parts.port,
            database=(parts.path or "").lstrip("/") or "postgres",
        )

    if settings.DB_HOST:
        return URL.create(
            "postgresql+asyncpg",
            username=settings.DB_USER or None,
            password=settings.DB_PASSWORD or None,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME or "postgres",
        )

    return None


# Supabase's Postgres pooler presents a certificate issued by
# "Supabase Intermediate 2021 CA", chaining to a SELF-SIGNED "Supabase Root 2021 CA"
# that is in no public trust store. Verified against the live database: full
# verification via the OS store and via certifi both fail with
# `self-signed certificate in certificate chain`.
#
# The previous code responded by turning verification off entirely
# (`verify_mode = CERT_NONE`), which encrypts the link but authenticates nothing —
# anything that can intercept the connection can present its own certificate and
# read or rewrite every query, including credentials and patient data.
#
# The fix is to trust Supabase's root explicitly. With this CA pinned, full
# verification (chain AND hostname) succeeds; a control test with the wrong CA is
# correctly rejected, which proves verification is actually being enforced.
_BUNDLED_SUPABASE_CA = Path(__file__).resolve().parent.parent / "certs" / "supabase-prod-ca-2021.crt"

# sha256 of the bundled file. Cross-check it against the certificate downloaded
# from your own Supabase dashboard (Settings -> Database -> SSL Configuration); a
# mismatch means the file was substituted and must not be trusted.
_SUPABASE_CA_SHA256 = "700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7"

# True once a connection has been built with real certificate verification.
# Surfaced by /api/admin/diagnostics so an operator can confirm it, rather than
# assuming.
DB_TLS_VERIFIED = False


def _resolve_ca_file() -> Path | None:
    """Pick the CA bundle to verify the database certificate against.

    `DB_SSL_ROOT_CERT` wins, so an operator can supply their own (a rotated
    Supabase root, or a different managed Postgres). Otherwise the bundled
    Supabase root is used if its digest still matches.
    """
    override = (getattr(settings, "DB_SSL_ROOT_CERT", "") or "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            logger.info(f"Database TLS: verifying against DB_SSL_ROOT_CERT ({path}).")
            return path
        logger.error(
            f"DB_SSL_ROOT_CERT points at {path}, which does not exist. "
            "Falling back to the bundled Supabase root."
        )

    if not _BUNDLED_SUPABASE_CA.is_file():
        return None

    digest = hashlib.sha256(_BUNDLED_SUPABASE_CA.read_bytes()).hexdigest()
    if digest != _SUPABASE_CA_SHA256:
        # Refuse a CA file we do not recognise rather than silently trusting it.
        logger.error(
            f"Bundled Supabase CA digest mismatch (got {digest}). Refusing to trust "
            "it. Replace the file or set DB_SSL_ROOT_CERT to a certificate you have "
            "verified yourself."
        )
        return None
    return _BUNDLED_SUPABASE_CA


def _connect_args(host: str) -> dict:
    """Connect args for the SQLAlchemy asyncpg adapter.

    The adapter pops `prepared_statement_cache_size` and
    `prepared_statement_name_func`; the rest (`statement_cache_size`,
    `server_settings`, `ssl`) go to asyncpg.connect().
    """
    global DB_TLS_VERIFIED
    args: dict = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        "server_settings": {"jit": "off"},
    }

    if (host or "").lower() in ("localhost", "127.0.0.1", ""):
        # Local Postgres over a loopback socket; TLS adds nothing here.
        return args

    ca_file = _resolve_ca_file()
    if ca_file is not None:
        ctx = ssl.create_default_context(cafile=str(ca_file))
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        DB_TLS_VERIFIED = True
        logger.info("Database TLS: full verification enabled (chain + hostname).")
    else:
        # Last resort: encrypted but UNAUTHENTICATED. Better than plaintext, but a
        # machine-in-the-middle can still impersonate the database.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        DB_TLS_VERIFIED = False
        logger.error(
            "Database TLS is ENCRYPTED BUT UNVERIFIED — no usable CA certificate was "
            "found, so the database's identity is not being checked and the "
            "connection is open to interception. Restore "
            "backend/certs/supabase-prod-ca-2021.crt or set DB_SSL_ROOT_CERT."
        )

    args["ssl"] = ctx
    return args


async def connect_to_db():
    """Create the async engine + sessionmaker and ensure the schema exists."""
    global engine, AsyncSessionLocal

    url = _build_url()
    if url is None:
        logger.error(
            "Database is not configured. Set DATABASE_URL, or the DB_HOST/"
            "DB_USER/DB_PASSWORD parts, in .env (Supabase connection)."
        )
        return

    try:
        engine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            connect_args=_connect_args(url.host),
        )
        AsyncSessionLocal = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        if settings.DB_AUTO_SCHEMA:
            # DEV CONVENIENCE ONLY. Idempotently create missing tables, then apply
            # the additive column migrations (create_all never ALTERs an existing
            # table). Every statement is safe to re-run.
            #
            # In production this is turned OFF and Alembic owns the schema
            # (`alembic upgrade head` as a deploy step), because this path has no
            # version history and no way to roll a change back. It also races when
            # several replicas boot at once.
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                for ddl in _COLUMN_MIGRATIONS:
                    await conn.execute(text(ddl))
            logger.info("Connected to Postgres (Supabase); schema auto-synced (dev mode).")
        else:
            # Verify the database is actually migrated instead of failing later on a
            # missing column, which surfaces as a confusing 500 mid-request.
            try:
                async with engine.connect() as conn:
                    stamped = (await conn.execute(
                        text("SELECT version_num FROM alembic_version LIMIT 1")
                    )).scalar()
                if stamped:
                    logger.info(f"Connected to Postgres; schema at migration {stamped}.")
                else:
                    logger.error(
                        "DB_AUTO_SCHEMA is off but no Alembic version is recorded. "
                        "Run `alembic upgrade head` (or `alembic stamp head` on an "
                        "already-correct database) before serving traffic."
                    )
            except Exception:
                logger.error(
                    "DB_AUTO_SCHEMA is off and the alembic_version table is missing. "
                    "Run `alembic upgrade head` before serving traffic."
                )
    except Exception as e:
        logger.error(f"Failed to connect to Postgres: {e}")
        engine = None
        AsyncSessionLocal = None


async def close_db_connection():
    global engine
    if engine is not None:
        await engine.dispose()
        logger.info("Postgres connection pool disposed.")


async def get_db():
    """FastAPI dependency that yields an AsyncSession per request."""
    if AsyncSessionLocal is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="Database is not configured. Set the Supabase DB settings in .env.",
        )
    async with AsyncSessionLocal() as session:
        yield session
