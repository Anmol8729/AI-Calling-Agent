# CLARIVO — SYSTEM ARCHITECTURE DOCUMENTATION

**Version:** 1.0 (Production Hardened)  
**Production URL:** `https://app.clarivo.net.in/`

---

## 1. High-Level System Architecture

Clarivo consists of three decoupled runtime planes:
1. **Frontend Plane (`frontend/`):** React 19 + Vite + Tailwind CSS SPA served via Caddy/static hosting, communicating over HTTPS REST (`/api/*`) and WebSockets (`/ws`).
2. **Backend API & Job Plane (`backend/`):** Async FastAPI + SQLAlchemy 2.0 + Alembic + SlowAPI + lease-locked background workers (`reminder_worker.py`, `call_sweeper.py`).
3. **Real-Time Voice AI Plane (`agent/`):** LiveKit Agents 1.6 Python worker running Silero VAD (`BVCTelephony`), Deepgram Nova-2 STT, `FallbackAdapter` LLM chain (`Groq qwen/qwen3.8-27b` ➔ `Gemini Flash Lite` ➔ `MiniMax M3.1`), and MiniMax `speech-2.8-turbo` TTS with RAM/disk PCM caching.

---

## 2. Frontend ↔ Backend Communication

- **HTTP Client:** Configured in `frontend/src/lib/api.js` using Axios with `withCredentials: true`.
- **Clinic User Auth:** Sends `Authorization: Bearer <jwt>` from `localStorage`.
- **Designated Admin Auth:** Uses `HttpOnly`, `SameSite=Lax`, `Secure` (prod/staging) cookie `clarivo_admin_session` paired with `X-CSRF-Token` header read from `clarivo_csrf_token`.
- **Real-Time Events:** Authenticated WebSocket (`backend/websocket/handler.py`) bridged across processes via Redis Pub/Sub (`backend/services/events.py`).

---

## 3. Database Architecture (`backend/models/__init__.py`)

- **Engine:** PostgreSQL 16 via `asyncpg` with pinned CA TLS (`backend/certs/supabase-prod-ca-2021.crt`).
- **Core Tables:**
  - `tenants` — Clinic accounts, `status` (`pending` / `active` / `suspended`), `booking_mode` (`time` / `token`), `subscription`, `monthly_call_limit`, `number_limit`.
  - `users` — Multi-tenant users (`doctor`, `staff`), `token_version` (session revocation), `failed_login_attempts`, `locked_until`, `email_verified_at`.
  - `patients` — Clinic-scoped patient records (`clinic_id` FK), `source` (`agent` / `manual`), JSONB `history`.
  - `appointments` — Clinic-scoped bookings protected by `pg_advisory_xact_lock` and partial unique indexes.
  - `call_logs` — Call metadata, duration, status, JSONB `transcript`.
  - `sip_trunks` & `phone_numbers` — Per-tenant LiveKit SIP inbound trunks (`Bring-Your-Own-Number` Option A).
  - `audit_logs` — Append-only security & compliance event trail.
  - `job_leases` — Distributed lease table for background job leader election.

---

## 4. Authentication & Single-Admin Session Architecture

- **Password Hashing:** Argon2id (`argon2-cffi`, `Type.ID`) for all new hashes and admin provisioning, with automatic backward verification and transparent re-hashing of legacy `bcrypt` hashes on login.
- **Single Designated Admin (`ADMIN_EMAIL`):**
  - Only one designated email is granted `is_superadmin` access.
  - Public `/api/auth/register` and `/api/auth/oauth/google` block creating the designated admin email.
  - Provisioned exclusively via `scripts/tools/provision_admin.py` (never hardcoded).
  - **Single Active Session:** Logging in atomically increments `users.token_version`, revoking all prior admin sessions across devices immediately.
  - **Idle Timeout:** `ADMIN_SESSION_IDLE_MINUTES` (default 30 min) revokes idle admin sessions automatically.

---

## 5. External Integrations & Telephony Flow

1. **Telephony (Option A / BYON):** Clinic owns its phone number with its telecom operator and forwards SIP calls to its dedicated LiveKit SIP Inbound Trunk (`services/livekit_sip.py`). Clarivo incurs ₹0.00 telecom fees.
2. **Voice Pipeline (`agent/main.py`):**
   - `POST /api/calls/agent-context` issues a short-lived, single-call scoped JWT (`_CALL_TOKEN` ContextVar) restricted to one `clinic_id` and `call_id`.
   - 4-minute hard call duration watchdog (`AGENT_MAX_CALL_DURATION_SEC=240`) politely wraps up and disconnects calls at 240 seconds.
3. **Billing & Messaging:** Razorpay checkout + HMAC-verified webhooks (`backend/routes/billing.py`) and Meta WhatsApp Cloud API (`backend/services/whatsapp.py`).
