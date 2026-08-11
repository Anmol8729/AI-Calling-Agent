"""
SQLAlchemy ORM models for the VoxPilot backend (Supabase Postgres).

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = mapped_column(String(255), nullable=False)
    subscription = mapped_column(String(50), nullable=False, default="free")
    # How this tenant books: "time" (fixed time slots) or "token" (daily queue
    # number — common for Indian doctor clinics).
    booking_mode = mapped_column(String(20), nullable=False, default="time")
    # "Now serving" state for token mode (per-day; resets when the date changes).
    queue_current_number = mapped_column(Integer, nullable=False, default=0)
    queue_current_date = mapped_column(String(10), nullable=True)  # YYYY-MM-DD (naive local)
    # Optional per-tenant monthly call allowance override. When set (any positive
    # int), it wins over the subscription plan's default allowance — used for
    # custom/enterprise deals. See services/plans.py.
    monthly_call_limit = mapped_column(Integer, nullable=True)
    # Vertical this tenant operates in (clinic, real_estate, restaurant, ...).
    # Drives the starter template picked at sign-up; see services/industry_templates.py.
    industry = mapped_column(String(50), nullable=True)
    # Where new-booking alert emails are sent. Falls back to clinic owner emails
    # when empty. See services/notifications.py.
    notify_email = mapped_column(String(255), nullable=True)
    # Per-tenant WhatsApp (Meta Cloud API) config. When set, this tenant sends
    # from its OWN number; otherwise it falls back to the platform .env values.
    # access_token is a secret — masked in API responses, never returned raw.
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
    __tablename__ = "users"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = mapped_column(String(255), nullable=False, unique=True)
    password_hash = mapped_column(String(255), nullable=False)
    name = mapped_column(String(255), nullable=False)
    role = mapped_column(String(50), nullable=False, default="doctor")
    clinic_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


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
    source = mapped_column(String(20), nullable=False, default="agent")
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
    purpose = mapped_column(String(20), nullable=False, default="reset")  # reset | invite
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
    "PasswordResetToken", "PhoneNumber", "UpgradeRequest", "Payment",
    "WhatsAppMessage", "DemoRequest",
]
