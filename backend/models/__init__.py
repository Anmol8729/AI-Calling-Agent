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
    # Lifecycle: "pending" (awaiting admin approval), "active" (approved), "suspended".
    # Existing rows default to "active" so live businesses are never locked out.
    status = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default=text("'active'"),
        index=True,
    )
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
    # Per-tenant override for how many phone numbers this client may connect. Same
    # pattern as monthly_call_limit: set it to agree a larger allowance for one
    # customer without inventing a new plan. Leaving it None applies the plan's
    # included_numbers.
    #
    # No longer a spend cap. It was one while Clarivo subscribed to the DIDs itself
    # (~₹100 setup plus ₹500/month each); customers now hold their own numbers with
    # their own operator, so this limits a feature rather than a bill and can be raised
    # freely. See services/plans.py.
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
    # When these credentials last passed a live check against the Cloud API.
    # NULL means "never verified", which is what the dashboard shows as
    # "Not Connected". It is NOT the same as "a token is stored" — a stored token
    # can still be expired or point at a number this app cannot see, so the badge
    # has to reflect a real probe. Cleared whenever the id or token changes,
    # otherwise the badge would keep vouching for credentials nobody checked.
    whatsapp_verified_at = mapped_column(DateTime, nullable=True)
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
    # "agent" = created by the voice agent during a live call.
    # "manual" = created by a logged-in user from the Contacts page.
    # server_default as well as default: this column is NOT NULL and the table
    # already holds rows, so the ALTER that adds it needs a value for them. It also
    # matches what backend/db/schema.sql declares, which keeps autogenerate quiet.
    source = mapped_column(
        String(20), nullable=False, default="agent", server_default=text("'agent'")
    )
    # The user who manually created this record (NULL for agent-created records
    # and for any row created before this column was added).
    created_by = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    """A phone number that reaches this tenant's assistant.

    Two columns describe two different things and both are needed to route a call:

      * `status` is the CUSTOMER'S intent — "I want this line answered" — and is what
        the dashboard's Activate/Deactivate button writes.
      * `verification_status` is OUR evidence that the number really belongs to them.

    Keeping them apart matters because they can disagree in both directions: a
    verified number can be deliberately paused, and a brand-new number is switched
    on by its owner long before we have proof. Collapsing them into one field meant
    the only honest default was "active", which is how an unverified number could
    start taking calls the moment somebody typed it in.

    On why proof is needed at all: a number is claimable exactly once platform-wide,
    so without proof the first account to type a competitor's number would capture
    that competitor's calls. Verification is described on SipTrunk below — it falls
    out of the trunk design rather than needing an SMS or OTP provider, which is
    fortunate, because this codebase has neither.
    """

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
    # Who the subscriber of record is:
    #   bring_your_own       - the customer holds it with their own operator and
    #                          forwards it to us. The supported model: they sign
    #                          their own CAF/KYC and we are only the software layer.
    #   platform_provisioned - legacy. Clarivo claimed it from its own Vobiz account
    #                          and handed it over, which put OUR name on the CAF for
    #                          a line somebody else uses. Gated off behind
    #                          settings.ALLOW_PLATFORM_NUMBERS; see
    #                          docs/PLAN-number-ownership.md.
    # Until this column existed the distinction survived only in an audit-log detail
    # blob, so the database could not answer "which numbers are we the subscriber of?"
    # — the first question anyone reviewing the licensing position asks.
    # server_default as well as default: migrations/env.py runs with
    # compare_server_default=True, so a default that exists only in Python would show
    # up forever as pending drift in `alembic check`. It also means a hand-written
    # INSERT gets a sane value instead of failing the NOT NULL.
    source = mapped_column(
        String(30), nullable=False, default="bring_your_own",
        server_default="bring_your_own",
    )
    # pending | verified. No "failed" state: a failed attempt is simply one that has
    # not happened yet, and a stored failure would need expiring to avoid stranding a
    # customer who fixed their operator config an hour later.
    verification_status = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending",
    )
    # When the first authenticated call proved ownership. NULL means never.
    verified_at = mapped_column(DateTime, nullable=True)
    # The customer's telephony operator, e.g. "Airtel", "Tata Tele", "Exotel".
    # Informational only — nothing branches on it. It exists because support's first
    # question on a routing problem is "who is your provider?", and because it is the
    # written record that the number belongs to their account, not ours.
    provider = mapped_column(String(60), nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class SipTrunk(Base):
    """The per-tenant SIP entry point a customer's operator forwards calls into.

    ONE row per clinic. It exists because the trunk stopped being infrastructure and
    became a customer-facing resource.

    Before this, a single LiveKit inbound trunk — created by hand in the LiveKit
    console — served every tenant, and the only thing distinguishing one caller's
    business from another's was the dialed number. That works when we own every
    number. It does not work when customers bring their own, for two reasons:

      1. **Nothing to authenticate.** A shared trunk has one set of credentials, so
         any party who obtained them could present any number and be answered as
         that tenant.
      2. **Nothing to prove ownership with.** We would be taking the customer's word
         that the number is theirs.

    Giving each tenant its own trunk solves both at once, and the second one for
    free. The digest credentials below are generated by us and displayed in exactly
    one place: that tenant's own dashboard. So when a call arrives authenticated with
    them, whoever configured the forwarding for the dialed number is necessarily the
    party holding this tenant's secret. That IS the ownership proof — which is why
    `PhoneNumber.verification_status` can be satisfied by the customer's first test
    call instead of by an SMS OTP we have no provider for.

    The matching guard lives in the resolution path: a call arriving on this trunk
    for a number belonging to a DIFFERENT clinic is rejected rather than answered.
    Without that, per-tenant credentials would authenticate the tenant but still let
    them claim anyone's number.

    A row can exist before the LiveKit trunk does (`status="pending"`) — see the
    column comment. That is deliberate: the dashboard must be able to tell a customer
    "we are still setting this up" instead of failing their request outright.
    """

    __tablename__ = "sip_trunks"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # UNIQUE, not just indexed: one trunk per clinic is the invariant the whole
    # design rests on. A second row would silently split a tenant's numbers across
    # two trunks with two different passwords.
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # LiveKit's own ids (ST_… and SDR_…). NULL while status="pending".
    livekit_trunk_id = mapped_column(String(64), nullable=True, unique=True)
    livekit_dispatch_rule_id = mapped_column(String(64), nullable=True)
    # Digest credentials the customer gives their operator. Generated here, never
    # chosen by the customer, and rotatable from the dashboard.
    #
    # Stored in plaintext, matching tenants.whatsapp_access_token. That is a real
    # tradeoff, so the reasoning: this authenticates INBOUND calls only, so unlike a
    # leaked outbound SIP password it cannot be used to place calls at our expense.
    # The worst case is forged calls INTO one tenant's assistant — quota and LLM
    # spend, and junk appointments — which is why `allowed_addresses` and the rotate
    # endpoint exist. Encrypting it would mean introducing a key to manage and lose,
    # for a codebase that currently has no encryption-at-rest anywhere; that is worth
    # doing as a deliberate piece of work, not as a side effect of this change.
    auth_username = mapped_column(String(64), nullable=False)
    auth_password = mapped_column(String(128), nullable=False)
    # Host the operator points at, captured at creation time rather than derived on
    # read: if LIVEKIT_URL or LIVEKIT_SIP_HOST is ever changed we still know what we
    # told this customer to configure, which is the difference between diagnosing a
    # broken trunk and guessing about it.
    sip_host = mapped_column(String(255), nullable=True)
    # Optional comma-separated IP/CIDR allowlist for the operator's signalling
    # addresses, passed straight through to the trunk. This is the control that turns
    # the credentials from "a shared secret" into "a shared secret usable from two
    # known hosts". Left NULL by default because a wrong value breaks every call for
    # that tenant, and most customers do not know their operator's signalling IPs.
    allowed_addresses = mapped_column(Text, nullable=True)
    # pending  - row exists, LiveKit trunk does not (credentials not yet usable).
    #            Happens when LIVEKIT_* is unconfigured or LiveKit rejected the call.
    # active   - trunk exists and is accepting calls.
    status = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending",
    )
    # Why the last sync failed, shown to the tenant instead of a bare "pending".
    # Cleared on success. Never holds credentials.
    last_error = mapped_column(Text, nullable=True)
    # Last time the trunk's number list was successfully pushed to LiveKit. Lets a
    # drifted trunk be spotted without calling out to LiveKit on every page load.
    synced_at = mapped_column(DateTime, nullable=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


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


class DemoRequest(Base):
    """Marketing lead captured from the landing page 'Request a callback' form.

    Not tied to a tenant — this is a top-level record. Status lifecycle:
      pending -> contacted -> converted | dismissed
    """
    __tablename__ = "demo_requests"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = mapped_column(String(255), nullable=False)
    phone = mapped_column(String(50), nullable=False)
    email = mapped_column(String(255), nullable=True)
    note = mapped_column(Text, nullable=True)
    # pending | contacted | converted | dismissed
    status = mapped_column(String(20), nullable=False, default="pending", index=True)
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


__all__ = [
    "Base", "Tenant", "User", "Patient", "Appointment", "CallLog",
    "PasswordResetToken", "PhoneNumber", "SipTrunk", "UpgradeRequest", "Payment",
    "WhatsAppMessage", "DemoRequest",
]
