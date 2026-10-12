# Telephony & Call Flow Architecture Guide

This document outlines the call routing, SIP trunk architecture, and call transfer functionality in Clarivo.

---

## 1. Architecture Overview

Clarivo handles incoming telephone calls through a modern SIP-to-WebRTC bridge:

```
[Patient / Caller]
       │
       ▼ (PSTN / Mobile Carrier)
[SIP Trunk: Vobiz or Client Operator]
       │
       ▼ (SIP Forwarding to per-tenant Inbound Trunk)
[LiveKit Cloud SIP Bridge]
       │
       ▼ (WebRTC Audio Stream)
[Clarivo Voice Worker: agent/main.py]
  ├─ Silero VAD (Noise suppression)
  ├─ Deepgram STT (nova-2 Hindi/multilingual)
  ├─ LLM Chain: Groq / Gemini / MiniMax
  └─ MiniMax TTS + Soft-Knee Volume Limiter
       │
       ▼ (Scoped internal REST token)
[Clarivo FastAPI Backend + Supabase PostgreSQL]
```

---

## 2. Phone Number Options

### Option A: Bring Your Own Number (Supported Production Model)
Clients retain ownership of their phone number with their local telecom operator (Airtel, Tata Tele, Jio, Exotel, etc.) and forward calls to a dedicated **per-tenant LiveKit SIP Inbound Trunk**:
1. Business navigates to **Setup &rarr; Phone Numbers** in the dashboard.
2. The dashboard displays the unique SIP URI and digest credentials for their dedicated trunk.
3. The operator forwards inbound calls to that SIP URI.
4. The first test call automatically authenticates and verifies the number.

### Option B: Platform Numbers (Legacy Vobiz Inventory)
If `ALLOW_PLATFORM_NUMBERS=true` in `.env`, numbers can be claimed directly from the platform's Vobiz account via the dashboard.

---

## 3. Running the System in Development

### Start the Backend
```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```
> Note: `--host 0.0.0.0` is recommended when using tunnels like ngrok.

### Start the Voice Agent
```powershell
cd agent
.\.venv\Scripts\python.exe main.py dev
```

### Start the Dashboard
```powershell
cd frontend
npm run dev
```
Open `http://localhost:5173` or `http://127.0.0.1:3000` in your browser.

---

## 4. Testing Endpoints & Diagnostics

- **Health check**: `curl http://localhost:8000/health` (returns database and API status).
- **WebSocket notifications**: `python test_websocket.py` (verifies unauthorized connection closure and authenticated connection flow).
- **Automated test suite**: `pytest backend/tests` (139+ security contract and unit tests).
