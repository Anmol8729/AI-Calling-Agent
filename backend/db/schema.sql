-- Clarivo — Supabase Postgres schema
--
-- This file is OPTIONAL. The backend calls SQLAlchemy's create_all() on startup,
-- which creates any missing tables automatically. Use this script if you prefer
-- to provision the schema yourself via the Supabase SQL editor.
--
-- Multi-tenancy is enforced in the application layer (every query filters by
-- clinic_id) using the backend's own JWT auth. The app connects with the
-- Postgres role, so Row Level Security is intentionally NOT used here. Do not
-- expose these tables through the Supabase client/anon key without adding RLS.

create extension if not exists "pgcrypto";  -- provides gen_random_uuid()

-- ===== tenants (clinics) =====
create table if not exists tenants (
    id               uuid primary key default gen_random_uuid(),
    name               varchar(255) not null,
    subscription       varchar(50)  not null default 'free',
    booking_mode         varchar(20)  not null default 'time',  -- 'time' (slots) | 'token' (daily queue)
    queue_current_number integer      not null default 0,       -- token mode: "now serving" number
    queue_current_date   varchar(10),                           -- YYYY-MM-DD the queue counter belongs to
    monthly_call_limit integer,
    industry           varchar(50),
    notify_email       varchar(255),
    whatsapp_phone_number_id   varchar(64),
    whatsapp_access_token      text,
    whatsapp_template_lang     varchar(20),
    whatsapp_confirm_template  varchar(100),
    whatsapp_reminder_template varchar(100),
    did                varchar(50)  unique,
    system_prompt    text,
    initial_greeting text,
    knowledge_base   text,
    voice            varchar(100),
    language         varchar(20),
    llm_model        varchar(100),
    created_at       timestamp    not null default (now() at time zone 'utc')
);

-- ===== users =====
create table if not exists users (
    id            uuid primary key default gen_random_uuid(),
    email         varchar(255) not null unique,
    password_hash varchar(255) not null,
    name          varchar(255) not null,
    role          varchar(50)  not null default 'doctor',
    clinic_id     uuid references tenants(id) on delete set null,
    created_at    timestamp    not null default (now() at time zone 'utc')
);
create index if not exists ix_users_clinic_id on users(clinic_id);

-- ===== patients =====
create table if not exists patients (
    id              uuid primary key default gen_random_uuid(),
    clinic_id       uuid not null references tenants(id) on delete cascade,
    name            varchar(255) not null,
    phone           varchar(50)  not null,
    email           varchar(255),
    age             integer,
    gender          varchar(20),
    history         jsonb not null default '[]'::jsonb,
    follow_up_notes text,
    created_at      timestamp not null default (now() at time zone 'utc'),
    constraint uq_patient_clinic_phone unique (clinic_id, phone)
);
create index if not exists ix_patients_clinic_id on patients(clinic_id);

-- ===== appointments =====
create table if not exists appointments (
    id               uuid primary key default gen_random_uuid(),
    clinic_id        uuid not null references tenants(id) on delete cascade,
    patient_id       varchar(64),         -- patient uuid (as text) or 'new'
    patient_name     varchar(255) not null,
    appointment_date text not null,       -- human-readable display string
    appointment_at   timestamp,           -- structured start (naive local) for conflict detection
    duration_min     integer not null default 30,
    token_number     integer,             -- token/queue mode: assigned daily number
    token_date       varchar(10),         -- YYYY-MM-DD (naive local) the token belongs to
    phone            varchar(50),         -- customer phone for WhatsApp confirmation/reminder
    reminder_sent    boolean not null default false,
    reason           text,
    status           varchar(50) not null default 'scheduled',
    created_at       timestamp not null default (now() at time zone 'utc')
);
create index if not exists ix_appointments_clinic_id on appointments(clinic_id);
create index if not exists ix_appointments_status on appointments(status);
create index if not exists ix_appointments_appointment_at on appointments(appointment_at);

-- ===== call_logs =====
create table if not exists call_logs (
    id            uuid primary key default gen_random_uuid(),
    call_id       varchar(255) not null unique,
    clinic_id     uuid references tenants(id) on delete set null,
    caller_name   varchar(255),
    phone         varchar(50),
    direction     varchar(20),
    duration      integer not null default 0,
    status        varchar(50),
    transcript    jsonb not null default '[]'::jsonb,
    recording_url text,
    created_at    timestamp not null default (now() at time zone 'utc')
);
create index if not exists ix_call_logs_clinic_id on call_logs(clinic_id);

-- ===== password_reset_tokens (password reset + team invite links) =====
create table if not exists password_reset_tokens (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    token_hash  varchar(64) not null unique,   -- sha256 hex of the token
    purpose     varchar(20) not null default 'reset',  -- reset | invite
    expires_at  timestamp not null,
    used_at     timestamp,
    created_at  timestamp not null default (now() at time zone 'utc')
);
create index if not exists ix_password_reset_tokens_user_id on password_reset_tokens(user_id);

-- ===== phone_numbers (inbound DIDs connected by each clinic) =====
create table if not exists phone_numbers (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references tenants(id) on delete cascade,
    number      varchar(32) not null unique,
    label       varchar(100),
    status      varchar(20) not null default 'active',  -- active | inactive
    created_at  timestamp not null default (now() at time zone 'utc')
);
create index if not exists ix_phone_numbers_clinic_id on phone_numbers(clinic_id);

-- ===== upgrade_requests (client asks to move to another plan) =====
create table if not exists upgrade_requests (
    id             uuid primary key default gen_random_uuid(),
    clinic_id      uuid not null references tenants(id) on delete cascade,
    requested_by   varchar(64),
    current_plan   varchar(50),
    requested_plan varchar(50) not null,
    note           text,
    status         varchar(20) not null default 'pending',  -- pending | approved | rejected
    created_at     timestamp not null default (now() at time zone 'utc'),
    resolved_at    timestamp
);
create index if not exists ix_upgrade_requests_clinic_id on upgrade_requests(clinic_id);
create index if not exists ix_upgrade_requests_status on upgrade_requests(status);

-- ===== whatsapp_messages (log of confirmations + reminders sent) =====
create table if not exists whatsapp_messages (
    id          uuid primary key default gen_random_uuid(),
    clinic_id   uuid not null references tenants(id) on delete cascade,
    to_phone    varchar(50),
    kind        varchar(20) not null default 'confirmation',  -- confirmation | reminder
    template    varchar(100),
    body        text,
    status      varchar(20) not null default 'sent',          -- sent | failed
    error       text,
    created_at  timestamp not null default (now() at time zone 'utc')
);
create index if not exists ix_whatsapp_messages_clinic_id on whatsapp_messages(clinic_id);
create index if not exists ix_whatsapp_messages_created_at on whatsapp_messages(created_at);

-- ===== payments (Razorpay orders + captured payments) =====
create table if not exists payments (
    id                  uuid primary key default gen_random_uuid(),
    clinic_id           uuid not null references tenants(id) on delete cascade,
    plan_key            varchar(50) not null,
    amount_inr          integer not null default 0,
    currency            varchar(10) not null default 'INR',
    razorpay_order_id   varchar(64) not null unique,
    razorpay_payment_id varchar(64),
    status              varchar(20) not null default 'created',  -- created | paid | failed
    created_at          timestamp not null default (now() at time zone 'utc'),
    paid_at             timestamp
);
create index if not exists ix_payments_clinic_id on payments(clinic_id);
create index if not exists ix_payments_order_id on payments(razorpay_order_id);
create index if not exists ix_payments_status on payments(status);
