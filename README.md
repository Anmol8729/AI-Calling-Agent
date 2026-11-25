# Clarivo — Autonomous Multi-Tenant AI Voice Receptionist

[![CI](https://github.com/Anmol8729/AI-Calling-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Anmol8729/AI-Calling-Agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![LiveKit](https://img.shields.io/badge/LiveKit-Agents_1.6-blueviolet)
![License](https://img.shields.io/badge/License-MIT-green)

**Clarivo** is a production-grade, multi-tenant AI calling receptionist and clinical practice management SaaS built for medical clinics, dental offices, diagnostic labs, and appointment-driven businesses.

Clarivo answers live PSTN telephone calls over low-latency SIP trunking and WebRTC, conducts natural bilingual (Hindi & English) intake conversations, checks real-time doctor availability or queue tokens, books appointments with database-level concurrency safety, and triggers automated WhatsApp confirmations.

---

## Key Capabilities

- **Low-Latency Real-Time Voice Pipeline**
  - **VAD & Echo Suppression:** Silero VAD with `BVCTelephony` noise cancellation (`0.32s` silence detection, `0.25s–0.60s` endpointing).
  - **Streaming STT:** Deepgram `nova-2` (Hindi & multilingual) over persistent WebSocket streaming.
  - **Resilient LLM Fallback Chain:** `FallbackAdapter` routing **Groq (`qwen/qwen3.8-27b`, ~121ms TTFT)** ➔ **Google Gemini (`gemini-flash-lite-latest`)** ➔ **MiniMax (`MiniMax-M3.1-Flash`)** with chunk-level retry and schema sanitization.
  - **Streaming TTS & Caching:** MiniMax `speech-2.8-turbo` with two-tier RAM/disk PCM caching (`AGENT_TTS_CACHE=1`) and NumPy soft-knee audio limiting.
  - **Cost & Duration Guardrails:** Configurable 4-minute hard call duration watchdog (`AGENT_MAX_CALL_DURATION_SEC=240`) and caller-silence hangup (`AGENT_SILENCE_HANGUP_SEC=10`).
- **Bring-Your-Own-Number (BYON) SIP Architecture**
  - Clinics keep their own phone numbers with their existing telecom carrier and forward calls into dedicated per-tenant **LiveKit SIP Inbound Trunks** with digest credentials—eliminating telecom licensing overhead and carrier billing exposure.
- **Enterprise Multi-Tenancy & Security**
  - Strict `clinic_id` isolation across all routes, database models, WebSockets, and CRM views.
  - Short-lived, per-call scoped JWT tokens for voice agent workers (`_CALL_TOKEN` ContextVar isolation).
  - JWT session revocation (`token_version`), account lockout, SlowAPI rate limiting, pinned PostgreSQL TLS CA verification, and append-only `audit_logs`.
- **Concurrency-Safe Clinical Scheduling**
  - Supports both fixed time slots and daily queue/token workflows protected by PostgreSQL advisory transaction locks (`pg_advisory_xact_lock`).
  - Distributed lease-locked background workers (`job_leases`) for automated WhatsApp appointment reminders and stale-call sweeping.

---

## System Architecture

```text
  Patient PSTN Caller
          │
          ▼  (SIP Forward via Clinic's Operator)
  LiveKit Cloud SIP Inbound Trunk (India South)
          │
          ▼  (WebRTC Audio Tracks)
  Clarivo Voice Worker (agent/main.py)
   ├─ Silero VAD + BVCTelephony
   ├─ Deepgram Nova-2 STT
   ├─ LLM Fallback: Groq (qwen3.8-27b) ➔ Gemini Flash Lite ➔ MiniMax
   └─ MiniMax speech-2.8-turbo TTS (+ RAM/Disk PCM Cache)
          │
          ▼  (Scoped Per-Call JWT + WebSocket)
  FastAPI Backend (backend/app.py)
   ├─ Multi-Tenant REST API & Razorpay Billing
   ├─ Rate Limiting (Redis / Memory)
   └─ Lease-Locked Reminder Worker & Call Sweeper
          │
          ▼  (asyncpg + Pinned CA TLS)
  PostgreSQL 16  •  Redis 7  •  React 19 SPA (frontend/)
```

---

## Repository Structure

```text
.
├── agent/                  # LiveKit AI voice worker, MiniMax streaming TTS, VAD & LLM pipeline
├── backend/                # FastAPI REST API, multi-tenant auth, Alembic migrations, jobs & tests
│   ├── config/             # Environment & security settings
│   ├── integrations/       # Vobiz, Gemini, MiniMax, WhatsApp, Razorpay clients
│   ├── migrations/         # Alembic schema version history
│   ├── models/             # SQLAlchemy 2.0 async models
│   ├── routes/             # Tenant-scoped API routers
│   ├── services/           # Business logic, LiveKit SIP, plans, audit & repository layer
│   └── tests/              # Pytest security, isolation, and regression test suite
├── frontend/               # React 19 + Vite + Tailwind CSS clinic & admin dashboard
├── docs/                   # Deployment guides, hosting checklist, and architecture notes
├── scripts/
│   ├── dev/                # Windows/PowerShell local development runners
│   └── tools/              # Pipeline diagnostics, WebSocket & test call utilities
├── .github/                # CI/CD workflows (backend, frontend, secret-scan) & PR/issue templates
├── Dockerfile              # Multi-stage production container build
├── docker-compose.yml      # Full-stack local/container orchestration
├── Makefile                # Unified developer commands
├── CONTRIBUTING.md         # Contribution guidelines & commit conventions
└── SECURITY.md             # Security architecture & vulnerability disclosure policy
```

---

## Quick Start

### Prerequisites
- **Python 3.11**
- **Node.js 20+** & **npm**
- **PostgreSQL 16** (or Supabase) & **Redis 7** (optional for local dev)

### Option 1: Docker Compose (Recommended)
```bash
cp .env.example .env
# Configure required API keys and database credentials in .env
make docker-up
```

### Option 2: Local Development
```bash
# 1. Configure environment
cp .env.example .env

# 2. Install dependencies
make install

# 3. Apply database migrations
make migrate

# 4. Start services (in separate terminals)
make dev-backend     # FastAPI on http://localhost:8000 (health: /health)
make dev-agent       # LiveKit Voice Worker
make dev-frontend    # React SPA on http://localhost:5173
```

---

## Testing & CI Verification

Every push and pull request runs automated checks in [`.github/workflows/ci.yml`](.github/workflows/ci.yml):
1. **Backend:** App import verification, `ruff check`, and `pytest backend/tests -v`.
2. **Secret Scan:** Regex credential scan, `.env` tracking check, and `.dockerignore` verification.
3. **Frontend:** `npm ci` and `npm run build` production bundle verification.

Run locally with:
```bash
make test
make lint
make build
```

---

## Documentation

- [Deployment Guide](docs/DEPLOYMENT.md) — Production Linux VM setup (Caddy, systemd, LiveKit region)
- [Hosting Checklist](docs/HOSTING-CHECKLIST.md) — Pre-flight production readiness checklist
- [Security Policy](SECURITY.md) — Security controls & responsible disclosure
- [Contributing Guide](CONTRIBUTING.md) — Development workflow & coding standards
