# Clarivo — Multi-Tenant AI Voice Receptionist SaaS 📞🩺

Clarivo is a production-ready, multi-tenant conversational voice AI receptionist SaaS designed specifically for medical practices, clinics, dental offices, labs, and service businesses (real estate, salons, hospitality).

Clarivo handles incoming telephone calls via low-latency SIP trunking and WebRTC, converses in natural Hindi and English, identifies returning callers, manages patient intake (name, age, reason for visit), checks live appointment availability or daily queue tokens, books appointments directly into the clinic's CRM, and sends instant automated WhatsApp notifications.

---

## 🚀 Key Features

*   **Multi-Tenant Architecture**: Complete tenant data isolation (`clinic_id`) across patients, appointment books, call histories, prompts, and knowledge bases.
*   **Carrier & SIP Trunk Integration**: Supports both Bring-Your-Own-Number (per-tenant SIP trunks via LiveKit Cloud) and Indian telephony integration (Vobiz SIP Trunking).
*   **Low-Latency AI Voice Pipeline**:
    *   **VAD & Noise Cancellation**: Silero VAD with `BVCTelephony` echo suppression.
    *   **Speech-to-Text**: Deepgram Nova-2 (`nova-2` Hindi & multilingual model) for high-accuracy phone audio transcription.
    *   **Resilient Fallback LLM Chain**: `FallbackAdapter` integrating Groq (`llama-3.3-70b-versatile`), Google Gemini (`gemini-flash-lite-latest`), and MiniMax (`MiniMax-Text-01`/`MiniMax-M3`) with provider schema sanitization.
    *   **Text-to-Speech**: Custom MiniMax streaming TTS (`speech-2.6-turbo` / `speech-02-turbo` / `speech-2.8`) with two-tier RAM/disk PCM audio caching and NumPy soft-knee volume limiter.
*   **Intelligent Clinic Intake & Scheduling**: Dynamic intent-gated booking supporting both fixed time slots and token/queue numbers, with database-level concurrency protection (`pg_advisory_xact_lock`).
*   **Security & Hardened Multi-Tenancy**:
    *   JWT session revocation (`token_version`), account lockout (`failed_login_attempts`), and password strength enforcement.
    *   Cryptographically separated per-call scoped tokens for the voice agent.
    *   Pinned TLS CA certificate for PostgreSQL connections.
    *   Comprehensive append-only audit trail (`audit_logs`).
*   **Automated Patient Care Campaigns**: Background worker elected via distributed database lease rows (`job_leases`) to dispatch appointment confirmations and WhatsApp reminders via Meta Cloud API.

---

## 🏗️ Architecture Overview

```
                 +--------------------------------------+
                 | Caller / Patient Telephone (PSTN)   |
                 +-------------------+------------------+
                                     |
                                     | Inbound SIP Call
                                     v
                 +-------------------+------------------+
                 | LiveKit SIP Inbound Trunk (Cloud)    |
                 | (Dedicated per-tenant credentials)   |
                 +-------------------+------------------+
                                     |
                                     | WebRTC Audio Tracks
                                     v
                 +-------------------+------------------+
                 | Clarivo Voice Worker (agent/main.py) |
                 |  - Silero VAD (Noise suppression)    |
                 |  - Deepgram STT (nova-2)             |
                 |  - Fallback LLMs (Groq/Gemini/Mini)  |
                 |  - MiniMax TTS + Audio Caching       |
                 +-------------------+------------------+
                                     |
           Internal Scoped JWT Token | Real-time WebSocket
           (clinic_id, call_id)      |
                                     v
                 +-------------------+------------------+
                 | FastAPI Backend (backend/app.py)     |
                 |  - Rate limiting (Redis / Memory)    |
                 |  - Lease-locked reminder worker      |
                 |  - Stale call sweeper loop           |
                 +-------------------+------------------+
                                     |
                                     v
                 +-------------------+------------------+
                 | PostgreSQL (Supabase ap-south-1)     |
                 | Pinned CA SSL, Alembic Migrations    |
                 +-------------------+------------------+
```

---

## 🛠️ Tech Stack

### Voice Agent (`agent/`)
*   **LiveKit Agents SDK 1.6.6**
*   **Deepgram STT** (`nova-2` Hindi & English)
*   **Groq, Google Gemini & MiniMax** (OpenAI-compatible streaming LLM chain)
*   **MiniMax TTS** with custom audio limiter and caching

### Backend (`backend/`)
*   **Python 3.11** & **FastAPI**
*   **PostgreSQL & SQLAlchemy 2.0 Async** (via `asyncpg` and Supabase pooler)
*   **Alembic** (database migrations)
*   **Redis** (optional rate-limiting & multi-process event bridge)
*   **SlowAPI** (token bucket rate limiting)

### Frontend (`frontend/`)
*   **React 19** & **Vite**
*   **Tailwind CSS**
*   **Zustand** (global state management)
*   **React Router v7** (with route code-splitting)
*   **Recharts** (call analytics visualization)
*   **Lucide React** (icons)

---

## ⚙️ Environment Configuration

Copy `.env.example` to `.env` in the repository root and configure the required keys:

```env
# App Configuration
ENV=development
SERVER_URL=http://localhost:8000
APP_BASE_URL=http://localhost:3000
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173
JWT_SECRET=generate-a-strong-secret-with-python-secrets-token-urlsafe-48
AGENT_INTERNAL_SECRET=generate-another-strong-secret-for-agent-internal-auth

# Database (Supabase PostgreSQL)
DATABASE_URL=
DB_USER=postgres.your_supabase_project_ref
DB_PASSWORD="your_db_password"
DB_HOST=aws-1-ap-south-1.pooler.supabase.com
DB_PORT=6543
DB_NAME=postgres

# LiveKit & Telephony
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret

# AI Providers
DEEPGRAM_API_KEY=your_deepgram_api_key
GROQ_API_KEY=your_groq_api_key
GEMINI_API_KEY=your_gemini_api_key
MINIMAX_API_KEY=your_minimax_api_key
MINIMAX_GROUP_ID=your_minimax_group_id
```

---

## 🏃‍♂️ Quick Start Setup

### Prerequisites
*   Python 3.10+ (Recommended: 3.11)
*   Node.js 18+ & npm
*   PostgreSQL database (or Supabase project)

### 1. Set Up the Backend
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate   # On Linux/macOS: source .venv/bin/activate

# Install verified production dependencies
pip install -r backend/requirements.txt

# Run migrations
alembic upgrade head

# Start FastAPI server
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```
Backend API will be live at `http://localhost:8000`. Health probe: `http://localhost:8000/health`.

### 2. Set Up the Voice Agent
```powershell
# In a separate terminal, set up the agent environment
cd agent
python -m venv .venv
.\.venv\Scripts\activate   # On Linux/macOS: source .venv/bin/activate

# Install agent dependencies
pip install -r requirements.txt

# Start agent in development mode
python main.py dev
```

### 3. Set Up the Frontend React Dashboard
```powershell
cd frontend
npm install
npm run dev
```
Dashboard will run at `http://localhost:5173` (or `http://127.0.0.1:3000`).

---

## 🧪 Testing & Verification

*   **Backend Security & Unit Tests**:
    ```powershell
    .\.venv\Scripts\python.exe -m pytest backend/tests -v
    ```
*   **Frontend Linting & Production Build**:
    ```powershell
    cd frontend
    npm run lint
    npm run build
    ```
*   **Integration Diagnostics**:
    ```powershell
    python run_pipeline_test.py
    ```

---

## 📖 Key Documentation

*   [`docs/DEPLOYMENT.md`](file:///c:/Users/acer/Desktop/AI-Calling-Agent/docs/DEPLOYMENT.md) — Production deployment on Linux VM (Caddy, LiveKit region, systemd services).
*   [`docs/SECURITY-REMEDIATION.md`](file:///c:/Users/acer/Desktop/AI-Calling-Agent/docs/SECURITY-REMEDIATION.md) — Complete security audit tracker and verified contracts.
*   [`docs/PLAN-number-ownership.md`](file:///c:/Users/acer/Desktop/AI-Calling-Agent/docs/PLAN-number-ownership.md) — Bring-Your-Own-Number per-tenant SIP trunking architecture.
*   [`docs/PLAN-tenant-approval.md`](file:///c:/Users/acer/Desktop/AI-Calling-Agent/docs/PLAN-tenant-approval.md) — Tenant onboarding, approval gating, and manual plan assignment.
