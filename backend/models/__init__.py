"""
SQLAlchemy ORM models for the Clarivo backend (Supabase Postgres).

These replace the previous MongoDB collections:
  tenants (clinics), users, patients, appointments, call_logs.

Notes:
- Primary keys are UUIDs (generated client-side via uuid4 so they work
  identically against any Postgres instance, including the Supabase pooler).
- `tenants.did` is UNIQUE but nullable; Postgres treats NULLs as distinct, so
  this mirrors the previous Mongo "sparse unique" index (many clinics may have
  no DID, but a present DID must be unique).
- `patients.history` and `call_logs.transcript` use JSONB (previously Mongo
  array fields). `transcript` holds a list of {"role", "content"} dicts.
- `appointments.patient_id` is stored as text (not a FK) because the AI tool
  flow may record "new"/unknown patients that have no patients row yet.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


class JobLease(Base):
    """Elects ONE process to run each background job.

    Declared as a model rather than raw DDL so Alembic's autogenerate can see it â€”
    otherwise every migration wants to drop it as an unknown table.

    A lease row and NOT a Postgres advisory lock: this database is behind Supabase's
    pooler, where separate sessions can share a backend connection and a lock
    outlives the process that took it (both measured against the live database), so
    an advisory lock leaks and wedges the job permanently. See
    backend/services/job_lock.py for the full reasoning.
    """

    __tablename__ = "job_leases"

    name = mapped_column(String(64), primary_key=True)
    owner = mapped_column(String(128), nullable=False)
    acquired_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    renewed_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    expires_at = mapped_column(DateTime(timezone=True), nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = mapped_column(String(255), nullable=False)
    subscription = mapped_column(String(50), nullable=False, default="free")
    # How this tenant books: "time" (fixed time slots) or "token" (daily queue
    # number â€” common for Indian doctor clinics).
    booking_mode = mapped_column(String(20), nullable=False, default="time")
    # "Now serving" state for token mode (per-day; resets when the date changes).
    queue_current_number = mapped_column(Integer, nullable=False, default=0)
    queue_current_date = mapped_column(String(10), nullable=True)  # YYYY-MM-DD (naive local)
    # Optional per-tenant monthly call allowance override. When set (any positive
    # int), it wins over the subscription plan's default allowance â€” used for
    # custom/enterprise deals. See services/plans.py.
    monthly_call_limit = mapped_column(Integer, nullable=True)
    # Per-tenant override for how many phone numbers this client may claim. Same
    # pattern as monthly_call_limit: set it to agree a larger allowance for one
    # customer without inventing a new plan. This is a SPEND cap â€” every DID costs
    # roughly â‚¹100 setup plus â‚¹500/month â€” so leaving it None applies the plan's
    # included_numbers. See services/plans.py.
    number_limit = mapped_column(Integer, nullable=True)
    # Vertical this tenant operates in (clinic, real_estate, restaurant, ...).
    # Drives the starter template picked at sign-up; see services/industry_templates.py.
    industry = mapped_column(String(50), nullable=True)
    # Where new-booking alert emails are sent. Falls back to clinic owner emails
    # when empty. See services/notifications.py.
    notify_email = mapped_column(String(255), nullable=True)
    # Per-tenant WhatsApp (Meta Cloud API) config. When set, this tenant sends
    # from its OWN number; otherwise it falls back to the platform .env values.
    # access_token is a secret â€” masked in API responses, never returned raw.
    whatsapp_phone_number_id = mapped_column(String(64), nullable=True)
    whatsapp_access_token = mapped_column(Text, nullable=True)
    whatsapp_template_lang = mapped_column(String(20), nullable=True)
    whatsapp_confirm_template = mapped_column(String(100), nullable=True)
    whatsapp_reminder_template = mapped_column(String(100), nullable=True)
    did = mapped_column(String(50), nullable=True, unique=True)
    system_prompt = mapped_column(Text, nullable=True)
    initial_greeting = mapped_column(Text, nullable=True)
    knowledge_base = mapped_column(Text, nullable=True)
    voice = mapped_column(String(100), nullable=True)
    language = mapped_column(String(20), nullable=True)
    llm_model = mapped_column(String(100), nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class User(Base):
    """The application's identity AND profile record.

    On the "profiles table" question: a separate `profiles` table is the usual
    Supabase pattern because `auth.users` cannot hold application columns. Here this
    table already fills that role — it carries `role`, `clinic_id` (the multi-tenant
    key that 59 queries scope by) and all the session-control columns. A second table
    holding `full_name` / `email` / `role` would create two sources of truth for the
    same facts plus a sync problem between them, so the profile fields that were
    genuinely missing (`avatar_url`, `updated_at`) were added here instead.

    Profile contract mapping:
        id -> id · full_name -> name · email -> email · avatar_url -> avatar_url
        role -> role · created_at -> created_at · updated_at -> updated_at
    """

    __tablename__ = "users"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = mapped_column(String(255), nullable=False, unique=True)
    # NULLABLE because an account created through Google sign-in has no password at
    # all. A placeholder hash would be indistinguishable from a real one; NULL says
    # plainly "this account cannot be signed in to with a password", and the login
    # route checks for exactly that.
    password_hash = mapped_column(String(255), nullable=True)
    name = mapped_column(String(255), nullable=False)
    role = mapped_column(String(50), nullable=False, default="doctor")
    # ----- identity provider link (Google sign-in via Supabase Auth) --------
    # Supabase's `auth.users.id` for accounts created or linked through Google.
    # NULL for password-only accounts. Unique, so one Google identity cannot be
    # attached to two different application accounts.
    supabase_user_id = mapped_column(String(64), nullable=True, unique=True)
    # Profile picture from the identity provider. Display only.
    avatar_url = mapped_column(Text, nullable=True)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ----- session control -------------------------------------------------
    # Access tokens are stateless JWTs, so before these columns existed there was
    # no way to end a session: logout only cleared the browser, and a stolen token
    # stayed valid for its full lifetime even after a password reset.
    #
    # token_version is embedded in every token as the `ver` claim and compared on
    # each request. Bumping it invalidates EVERY token for this user at once â€”
    # that is what makes password change/reset, "log out everywhere", and account
    # suspension actually take effect.
    token_version = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Set whenever the password changes; shown in security settings and useful
    # when investigating an account takeover.
    password_changed_at = mapped_column(DateTime, nullable=True)
    # False = suspended. Checked on every authenticated request, so access is
    # revoked on the next call rather than whenever the token happens to expire.
    is_active = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # ----- brute-force lockout ---------------------------------------------
    # Per-ACCOUNT, and in the database on purpose. The IP-keyed rate limit is
    # useless against credential stuffing (rotate IPs and you slip through) and it
    # resets on restart. These columns make the lockout follow the account instead,
    # and survive deploys.
    failed_login_attempts = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    locked_until = mapped_column(DateTime, nullable=True)
    last_login_at = mapped_column(DateTime, nullable=True)
    # When the owner of this address proved they control it. NULL = unverified.
    #
    # This matters more than usual here because platform super-admin is decided by
    # an EMAIL ALLOWLIST (SUPERADMIN_EMAILS). Without a mailbox check, whoever
    # registers an allowlisted address first becomes platform admin â€” no proof
    # required. `require_superadmin` therefore demands a verified address.
    #
    # Google sign-in sets this immediately: Google has already confirmed the address,
    # so sending our own verification email would be asking for proof we have.
    email_verified_at = mapped_column(DateTime, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    # Part of the profile contract below. Bumped whenever profile fields are synced
    # from the identity provider, so a stale name or avatar is visible as such.
    updated_at = mapped_column(DateTime, nullable=True, onupdate=datetime.utcnow)


class Patient(Base):
    __tablename__ = "patients"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = mapped_column(String(255), nullable=False)
    phone = mapped_column(String(50), nullable=False)
    email = mapped_column(String(255), nullable=True)
    age = mapped_column(Integer, nullable=True)
    gender = mapped_column(String(20), nullable=True)
    history = mapped_column(JSONB, nullable=False, default=list)
    follow_up_notes = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("clinic_id", "phone", name="uq_patient_clinic_phone"),
    )


class Appointment(Base):
    __tablename__ = "appointments"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stored as text: may be a patient UUID string or "new" for unknown callers.
    patient_id = mapped_column(String(64), nullable=True)
    patient_name = mapped_column(String(255), nullable=False)
    # Human-readable display string (kept for back-compat / free-text bookings).
    appointment_date = mapped_column(Text, nullable=False)
    # Structured start time (naive local wall-time) used for double-booking
    # detection, sorting, and reminders. Nullable for legacy free-text rows.
    appointment_at = mapped_column(DateTime, nullable=True, index=True)
    # Slot length in minutes; used for overlap/conflict detection.
    duration_min = mapped_column(Integer, nullable=False, default=30)
    # Token/queue mode: the assigned daily number and the day it belongs to.
    token_number = mapped_column(Integer, nullable=True)
    token_date = mapped_column(String(10), nullable=True)  # YYYY-MM-DD (naive local)
    # Customer phone for WhatsApp confirmation/reminder (from caller or the form).
    phone = mapped_column(String(50), nullable=True)
    # Set once the reminder has been sent, to avoid duplicate reminders.
    reminder_sent = mapped_column(Boolean, nullable=False, default=False)
    reason = mapped_column(Text, nullable=True)
    status = mapped_column(String(50), nullable=False, default="scheduled", index=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        # Calendar and conflict-detection reads are always scoped to one tenant and
        # ordered/filtered by start time.
        Index("ix_appointments_clinic_at", "clinic_id", "appointment_at"),
    )


class CallLog(Base):
    __tablename__ = "call_logs"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id = mapped_column(String(255), nullable=False, unique=True)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    caller_name = mapped_column(String(255), nullable=True)
    phone = mapped_column(String(50), nullable=True)
    direction = mapped_column(String(20), nullable=True)
    duration = mapped_column(Integer, nullable=False, default=0)
    status = mapped_column(String(50), nullable=True)
    transcript = mapped_column(JSONB, nullable=False, default=list)
    recording_url = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    # Bumped on every transcript turn. Needed because the agent's "call ended"
    # report is best-effort: on Windows, LiveKit's native layer panics during call
    # teardown and kills the worker before it fires, leaving the row stuck at
    # status="active", duration=0 forever. The sweeper
    # (backend/jobs/call_sweeper.py) uses this to close such rows with a real
    # duration instead of guessing, so the dashboard's live view and duration
    # stats stay honest.
    last_activity_at = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        # Every dashboard read is "this tenant, newest first". A plain clinic_id
        # index still made Postgres sort the whole tenant slice.
        Index("ix_call_logs_clinic_created", "clinic_id", created_at.desc()),
        # PARTIAL: the stale-call sweeper only scans rows still marked active,
        # which is a tiny fraction of the table.
        Index(
            "ix_call_logs_active",
            "created_at",
            postgresql_where=text("(status)::text = 'active'::text"),
        ),
    )


class AuditLog(Base):
    """Append-only record of security-relevant actions.

    Nothing recorded who did what before this: a suspended account, a plan change,
    a claimed phone number and a password reset all left no trace beyond an
    application log line that rotates away. That makes an incident impossible to
    reconstruct ("who removed that number?", "when was this account locked?") and is
    the kind of thing an enterprise buyer asks about directly.

    Written on a best-effort basis â€” an audit failure must never break the action
    the user asked for â€” but every write is a separate row and rows are never
    updated, so the history cannot be quietly rewritten through the app.
    """

    __tablename__ = "audit_logs"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Who. Nullable because some events have no signed-in actor (a failed login, a
    # password reset arriving with only a token).
    actor_user_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalised on purpose: the email must survive the user being deleted, or the
    # trail loses its meaning exactly when it matters most.
    actor_email = mapped_column(String(255), nullable=True)
    actor_role = mapped_column(String(50), nullable=True)
    # Which tenant the action affected. Nullable for platform-level events.
    clinic_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # What: a stable dotted verb, e.g. "auth.login", "number.provisioned".
    action = mapped_column(String(80), nullable=False, index=True)
    # What it acted on, e.g. ("phone_number", "<uuid>").
    target_type = mapped_column(String(50), nullable=True)
    target_id = mapped_column(String(255), nullable=True)
    # Free-form context. Must never hold secrets, tokens or passwords.
    detail = mapped_column(JSONB, nullable=False, default=dict)
    ip_address = mapped_column(String(64), nullable=True)
    user_agent = mapped_column(String(255), nullable=True)
    # "success" | "failure" â€” a failed attempt is often the interesting one.
    outcome = mapped_column(String(20), nullable=False, default="success")
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        # Audit reads are always "this tenant, newest first".
        Index("ix_audit_logs_clinic_created", "clinic_id", created_at.desc()),
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Only the SHA-256 hash of the token is stored, never the token itself.
    token_hash = mapped_column(String(64), nullable=False, unique=True)
    # reset | invite | verify
    purpose = mapped_column(String(20), nullable=False, default="reset")
    expires_at = mapped_column(DateTime, nullable=False)
    used_at = mapped_column(DateTime, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number = mapped_column(String(32), nullable=False, unique=True)
    label = mapped_column(String(100), nullable=True)
    status = mapped_column(String(20), nullable=False, default="active")  # active | inactive
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class UpgradeRequest(Base):
    __tablename__ = "upgrade_requests"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The user who requested it (stored as text id; informational, no hard FK).
    requested_by = mapped_column(String(64), nullable=True)
    current_plan = mapped_column(String(50), nullable=True)
    requested_plan = mapped_column(String(50), nullable=False)
    note = mapped_column(Text, nullable=True)
    status = mapped_column(String(20), nullable=False, default="pending", index=True)  # pending | approved | rejected
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    resolved_at = mapped_column(DateTime, nullable=True)


class Payment(Base):
    __tablename__ = "payments"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_key = mapped_column(String(50), nullable=False)
    amount_inr = mapped_column(Integer, nullable=False, default=0)
    currency = mapped_column(String(10), nullable=False, default="INR")
    # Razorpay identifiers. order_id is created first; payment_id is filled on success.
    razorpay_order_id = mapped_column(String(64), nullable=False, unique=True, index=True)
    razorpay_payment_id = mapped_column(String(64), nullable=True)
    status = mapped_column(String(20), nullable=False, default="created", index=True)  # created | paid | failed
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    paid_at = mapped_column(DateTime, nullable=True)


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_phone = mapped_column(String(50), nullable=True)
    kind = mapped_column(String(20), nullable=False, default="confirmation")  # confirmation | reminder
    template = mapped_column(String(100), nullable=True)
    # Readable preview of what was sent (templates live in Meta, so this is our summary).
    body = mapped_column(Text, nullable=True)
    status = mapped_column(String(20), nullable=False, default="sent")  # sent | failed
    error = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


__all__ = [
    "Base", "Tenant", "User", "Patient", "Appointment", "CallLog",
    "PasswordResetToken", "PhoneNumber", "UpgradeRequest", "Payment",
    "WhatsAppMessage",
]
