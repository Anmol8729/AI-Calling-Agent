# Clarivo - Multi-Tenant AI Medical Receptionist SaaS 📞🩺

Clarivo is a production-ready, multi-tenant conversational voice agent SaaS designed specifically for medical practices, clinics, hospitals, dentists, and labs. By leveraging advanced Large Language Models (LLMs), Voice Activity Detection (VAD), and low-latency VoIP integrations, Clarivo handles incoming patient calls, schedules appointments, logs patient interactions directly into a CRM, sends pill reminders, and redirects calls to human staff when necessary.

---

## 🚀 Key Features

*   **Multi-Tenant Architecture**: Isolate clinic configurations, patient CRMs, appointment books, call histories, and prompts per tenant.
*   **Indian Telephony Integration (Vobiz)**: Native integration with Vobiz SIP Trunking and Programmable Voice API for highly cost-effective calling.
*   **Low-Latency AI Pipeline**: Converts incoming 16-bit linear PCM (`audio/x-l16`) speech stream to text via a customized MiniMax ASR/STT wrapper, processes conversation context using MiniMax LLM, and streams voice replies back via MiniMax TTS.
*   **Role-Based Access Control (RBAC)**: Protects clinic dashboards and CRM data with secure JWT authentication for Administrators, Doctors, and Receptionists.
*   **CRM & Appointment Booking**: Dynamic scheduling tools with built-in database indexing, allowing the voice receptionist to check patient history, schedule slots, and update appointments in real-time.
*   **Automated Patient Care Campaigns**: Periodic cron scheduler for pill refills, patient checks, and appointment reminders.

---

## 🏗️ Architecture Design

```
                     +----------------------------+
                     |  Patient / Telephone Call   |
                     +--------------+-------------+
                                    |
                                    | SIP / VoIP
                                    v
                     +--------------+-------------+
                     |  Vobiz Voice Gateway       |
                     +--------------+-------------+
                                    |
                                    | WebSocket (Linear L16 PCM)
                                    v
                     +--------------+-------------+
                     |  FastAPI Middleware        |
                     +--------------+-------------+
                                    |
            +-----------------------+-----------------------+
            |                       |                       |
            v (Silence/VAD)         v                       v (Text-to-Speech)
   +--------+--------+     +--------+--------+     +--------+--------+
   |   MiniMax STT   |     |   MiniMax LLM   |     |   MiniMax TTS   |
   | (ASR Wrapper)   |     |   (Tool Calls)  |     |   (PCM Stream)  |
   +--------+--------+     +--------+--------+     +--------+--------+
            |                       |                       |
            | Text                  | DB Query / Write      | Audio Chunks
            +---------------------->+                       +----------> Vobiz
                                    |
                                    v
                           +--------+--------+
                           |  MongoDB Atlas  |
                           |  (CRM / Logs)   |
                           +-----------------+
```

---

## 🛠️ Tech Stack

### Backend
*   **Python 3.11** & **FastAPI**
*   **MongoDB & Motor Client** (Asynchronous DB driver)
*   **Redis & Celery** (Task Queue for campaigns and notifications)
*   **APScheduler** (Reminders scheduler)
*   **SlowAPI** (Token bucket rate limiting)

### Frontend
*   **React 19** & **Vite**
*   **Zustand** (Global state management)
*   **React Router v7**
*   **Recharts** (Call analytics visualization)
*   **Axios** (API client)

---

## ⚙️ Environment Configuration

Create a `.env` file in the root workspace directory with the following variables:

```env
# App Configuration
ENV=development
SERVER_URL=http://localhost:8000
JWT_SECRET=super-secret-receptionist-key-change-this-in-production

# Databases
MONGODB_URL=mongodb://localhost:27017
DATABASE_NAME=ai_receptionist
REDIS_URL=redis://localhost:6379/0

# MiniMax Configuration
MINIMAX_API_KEY=your_minimax_api_key_here
MINIMAX_GROUP_ID=your_minimax_group_id_here
MINIMAX_LLM_MODEL=abab6.5g-chat
MINIMAX_TTS_MODEL=speech-01-turbo
MINIMAX_TTS_VOICE=male-qn-qingse

# Vobiz Configuration
VOBIZ_SIP_DOMAIN=your-sip-domain.sip.vobiz.ai
VOBIZ_USERNAME=your_vobiz_username
VOBIZ_PASSWORD=your_vobiz_password
VOBIZ_OUTBOUND_NUMBER=+918045671200
DEFAULT_TRANSFER_NUMBER=+91XXXXXXXXXX
```

---

## 🏃‍♂️ Quick Start Setup

### Prerequisites
*   Docker & Docker Compose installed.
*   Python 3.10+ (Recommended: 3.11)

### 1. Launch Services (Local Dev Database & Redis)
Spin up local MongoDB and Redis instances in the background:
```bash
docker-compose up -d
```

### 2. Set Up the Backend
Create a virtual environment, activate it, and install python dependencies:
```bash
# From the root directory
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install requirements
pip install -r backend/requirements.txt

# Run the FastAPI server
python backend/app.py
```
The backend server will run on `http://localhost:8000`.

### 3. Set Up the Frontend React Dashboard
Install packages and start the Vite development server:
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## 📡 API Documentation Summary

### Authentication & Tenant Setup
*   `POST /api/auth/register`: Register a new doctor, create their clinic tenant, and generate a secure JWT token.
*   `POST /api/auth/login`: Authenticate clinic staff and return credentials.
*   `GET /api/auth/me`: Fetch details of the currently authenticated session.

### Patients & CRM
*   `GET /api/patients`: Retrieve patients registered under the logged-in doctor's clinic.
*   `POST /api/patients`: Manually create a new patient record.
*   `GET /api/patients/{patient_id}`: Read patient demographic and consultation history.

### Scheduling & Settings
*   `GET /api/appointments`: List scheduled appointments.
*   `POST /api/appointments`: Book an appointment slot.
*   `PUT /api/clinics/settings`: Customize AI voice receptionist parameters (prompts, greetings, routing DIDs).

### Calling & Webhooks
*   `POST /api/calls/twiml/inbound`: Receives inbound Vobiz calls and responds with bidirectional WebSocket Stream XML.
*   `POST /api/calls/twiml/outbound`: Callback triggered when outbound Vobiz calls are answered.
*   `POST /api/calls/twiml/transfer`: Generates Dial XML to redirect active calls.
*   `POST /api/calls/campaigns/trigger`: Dispatches bulk outbound calls natively via Vobiz.

---

## 📈 SaaS Scaling Guide

1.  **Distributed Task Workers**: Move Celery workers to independent server groups (e.g. AWS ECS or Kubernetes pods) to handle automated reminder campaigns for thousands of clinics concurrently.
2.  **DID Routing Isolation**: Scale the WebSocket servers horizontally and configure the Vobiz webhooks to query tenant DID metadata from a Redis cache layer for sub-millisecond route resolution.
3.  **Conversational Interruption (Barge-in)**: Vobiz handles user interruption using the `clearAudio` event. If a patient starts speaking while the AI is talking, listen to the STT active state, discard currently queued output on the WebSocket, and prepare an immediate reply.
