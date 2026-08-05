# Clarivo — Production Deployment (Ubuntu 24.04, India region)

Moves the voice agent + backend off the Windows laptop onto a Linux VM near the
LiveKit India region. This is the fix for the problems measured on the local setup:

| Measured locally | Cause | Fixed by this deploy |
|---|---|---|
| Gemini `ttft` 2.4–13.4s, `Request timed out` | home-link RTT 45–1064ms (23x jitter) | datacenter RTT, stable |
| Audio cutting mid-reply | TTS `ttfb` 0.6s per sentence → audible gap | lower, stable ttfb |
| 8.5 min `failed to connect to livekit` outage | home connection dropped | datacenter uptime |
| Context fetch ~1.9s per call | backend + Supabase across the home link | same region (~50ms) |
| `malformed serialized RtcError` panic, worker recycled every call | Windows-only LiveKit native bug | Linux → warm worker |
| 2 clients calling at once: untested/broken | per-call process recycle | `AGENT_RECYCLE_AFTER_CALL=0` |
| ngrok URL as `SERVER_URL` | no stable public host | real domain + HTTPS |

---

## 0. What runs where

| Component | Where | Cost |
|---|---|---|
| Voice agent (`agent/main.py`) | the VM | included |
| Backend (`backend/app.py`) + reminder worker | the VM (same box) | included |
| Frontend (`frontend/` static build) | Cloudflare Pages | free |
| Postgres | Supabase (already `ap-south-1`) | already paying |
| TLS certificates | Caddy + Let's Encrypt | free |

The reminder worker is **not** a separate service — `backend/app.py` starts it in its
lifespan (`asyncio.create_task(reminder_loop())`).

**No Redis, no Celery, no MongoDB.** `redis`, `celery` and `apscheduler` appear in
`requirements.txt` but are never imported anywhere in the codebase. Rate limiting is
in-memory (`backend/services/limiter.py` builds `Limiter(key_func=...)` with no
`storage_uri`) and reminders are the in-process asyncio task above. `REDIS_URL` in
`settings.py` is dead config. (`README.md` still describes a MongoDB + Celery stack —
that is stale; the live stack is Postgres on Supabase.)

### VM requirements

- **2 vCPU minimum**, 4 GB RAM, 40 GB disk. Measured idle usage is ~250 MB of
  services (agent ~197 MB + backend ~51 MB) plus the OS; budget **~200 MB per
  concurrent call** on top. The headroom is what you are paying for.
- **x86_64 / AMD64.** NOT ARM/Graviton/Ampere — `livekit-plugins-noise-cancellation`
  is a proprietary native library without a published arm64 build, and the agent uses
  `noise_cancellation.BVCTelephony()`.
- **India region** (Mumbai/Bangalore). LiveKit is in Hyderabad (`ohyderabad1a`) and
  Supabase is in Mumbai.
- Ubuntu 24.04 LTS.

### Ports

```
22   SSH
80   HTTP   (Let's Encrypt challenge only)
443  HTTPS  (backend API + webhooks)
```

No SIP ports. SIP goes Vobiz → LiveKit Cloud; it never touches this VM. The agent
only makes **outbound** connections (LiveKit, Gemini, MiniMax, Deepgram, Supabase).

---

## 1. First login and hardening

```bash
ssh root@<VM_IP>

# Create a non-root user to run the services
adduser --disabled-password --gecos "" clarivo

# Firewall
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw --force enable

timedatectl set-timezone Asia/Kolkata   # appointment_at is naive LOCAL time
```

> Timezone matters: `appointment_at` is stored as naive local wall-time and the
> reminder worker compares it against `datetime.now()`. A UTC server would send
> reminders 5.5 hours off.

---

## 2. System packages

```bash
apt update && apt upgrade -y
apt install -y python3.12 python3.12-venv python3-pip git \
               build-essential ca-certificates curl debian-keyring \
               debian-archive-keyring apt-transport-https
```

No `redis-server` — nothing in the codebase connects to it (see "What runs where").

Use **Python 3.12** (Ubuntu 24.04 default). Avoid 3.13: `audioop` was removed there,
and `agent/minimax_tts.py` falls back to it when numpy is missing — losing the TTS
gain limiter makes calls sound quiet. (Check in step 4 that numpy is importable.)

Install Caddy (automatic HTTPS):

```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy
```

---

## 3. Get the code onto the VM

Option A — git (preferred):

```bash
su - clarivo
git clone <YOUR_REPO_URL> ~/AI-Calling-Agent
```

Option B — copy from Windows (run in PowerShell **on the laptop**). Never copy
`.venv`, `node_modules`, or `.env`:

```powershell
cd C:\Users\acer\Desktop
scp -r .\AI-Calling-Agent clarivo@<VM_IP>:~/
```

---

## 4. Two virtualenvs (matching the local layout)

```bash
cd ~/AI-Calling-Agent

# Backend venv at the repo root
python3.12 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r backend/requirements.txt

# Agent venv inside agent/
python3.12 -m venv agent/.venv
./agent/.venv/bin/pip install --upgrade pip
./agent/.venv/bin/pip install -r agent/requirements.txt
```

Verify both import, and that numpy is present for the TTS limiter:

```bash
./.venv/bin/python -c "import backend.app; print('backend OK')"
cd agent && ../agent/.venv/bin/python -c "import numpy, main; print('agent OK, numpy', numpy.__version__)"; cd ..
```

If numpy is missing: `./agent/.venv/bin/pip install numpy`.

---

## 5. Production `.env`

One `.env` at the repo root is shared by the backend and the agent
(`agent/main.py` loads `../.env`). Copy the local file over, then change these:

```ini
ENV=production

# --- Public URLs (replace with your domain) ---
SERVER_URL=https://api.yourdomain.com      # Vobiz webhook target; replaces the ngrok URL
APP_BASE_URL=https://app.yourdomain.com    # password-reset / invite links are built from this
CORS_ORIGINS=https://app.yourdomain.com    # EXACT origin. No "*" — the API uses allow_credentials=True

# --- Auth: rotate this, the old value leaked via .env.example in git history ---
JWT_SECRET=<paste output of: python3 -c "import secrets; print(secrets.token_urlsafe(48))">

# --- Linux: the Windows teardown panic does not happen here ---
# 0 = one warm worker serves many calls. This is what unlocks concurrency, keeps the
# in-RAM TTS cache alive between calls, and removes the per-call LLM/TTS warm-up.
AGENT_RECYCLE_AFTER_CALL=0
AGENT_IDLE_PROCESSES=2                     # raise with expected concurrent calls

# --- Keep the tuning that was verified on real calls ---
AGENT_LLM_PROVIDER=gemini                  # Groq is faster but skipped the booking intake
AGENT_PREEMPTIVE=0                         # 1 caused "Request timed out" + 13s replies
MINIMAX_TTS_MODEL=speech-2.6-turbo
MINIMAX_TTS_EMOTION=
MINIMAX_TTS_SAMPLE_RATE=8000               # PSTN is 8kHz anyway; lower ttfb
AGENT_TTS_CACHE=1                          # greeting served from disk in ~3ms
```

Keep `AGENT_INTERNAL_SECRET` (or `JWT_SECRET`) consistent — the agent authenticates to
`/api/calls/agent-*` with it. Lock the file down:

```bash
chmod 600 ~/AI-Calling-Agent/.env
```

Also rotate, per the pre-launch checklist: the **WhatsApp access token** and the old
**Supabase DB password**, both of which are still in git history.

---

## 6. systemd services

These replace the `while ($true) { ... }` wrapper — systemd restarts on crash,
starts on boot, and gives you real logs.

**`/etc/systemd/system/clarivo-backend.service`**

```ini
[Unit]
Description=Clarivo backend (FastAPI + reminder worker)
After=network-online.target
Wants=network-online.target

[Service]
User=clarivo
WorkingDirectory=/home/clarivo/AI-Calling-Agent
# ONE worker only: the reminder worker runs inside the app, and multiple workers
# can send duplicate WhatsApp reminders (see backend/jobs/reminder_worker.py).
# Bound to 127.0.0.1 — Caddy is the only thing exposed to the internet.
ExecStart=/home/clarivo/AI-Calling-Agent/.venv/bin/python -m uvicorn backend.app:app \
          --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/clarivo-agent.service`**

```ini
[Unit]
Description=Clarivo LiveKit voice agent
After=network-online.target clarivo-backend.service
Wants=network-online.target

[Service]
User=clarivo
WorkingDirectory=/home/clarivo/AI-Calling-Agent/agent
# "start" is the production command; "dev" is the local development mode.
ExecStart=/home/clarivo/AI-Calling-Agent/agent/.venv/bin/python main.py start
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now clarivo-backend clarivo-agent
systemctl status clarivo-backend clarivo-agent
```

**Only ever run ONE agent.** Two agents register under the same `agent_name`
(`clarivo-inbound`) and LiveKit hands a call to whichever it picks — that caused a
whole debugging session locally. With systemd this is enforced, but before starting
manually, check:

```bash
pgrep -af "main.py"        # expect exactly one line
```

---

## 7. HTTPS + domain

DNS at your registrar:

| Record | Name | Value |
|---|---|---|
| A | `api` | `<VM_IP>` |
| CNAME | `app` | your Cloudflare Pages hostname (step 8) |

**`/etc/caddy/Caddyfile`**

```caddyfile
api.yourdomain.com {
	encode zstd gzip
	# WebSockets (the /media-stream path) pass through reverse_proxy unchanged.
	reverse_proxy 127.0.0.1:8000
}
```

```bash
systemctl reload caddy
curl -I https://api.yourdomain.com/      # expect HTTP 200, valid cert
```

Caddy obtains and renews the certificate automatically — no cron, no certbot.

---

## 8. Frontend on Cloudflare Pages (free)

```bash
cd frontend
# Point the SPA at the deployed API. The variable is VITE_API_URL (see
# frontend/.env.example) and it MUST include the /api suffix — the app appends
# route paths directly to it, so omitting /api gives 404s on every call.
echo "VITE_API_URL=https://api.yourdomain.com/api" > .env.production
npm ci && npm run build      # outputs dist/
```

In Cloudflare Pages: create a project → connect the repo (or upload `dist/`) →
build command `npm run build`, output directory `dist`, root directory `frontend`,
and set `VITE_API_URL=https://api.yourdomain.com/api` as a build environment
variable. Then add `app.yourdomain.com` as a custom domain.

---

## 9. Point Vobiz at the new URL

In the Vobiz dashboard, replace the ngrok webhook URL with:

```
https://api.yourdomain.com
```

The DID must stay assigned to trunk `ST_vwuaJbMMcLa4` — Vobiz does not auto-route
numbers. ngrok is no longer needed anywhere.

---

## 10. Verify (in this order)

```bash
# 1. Services alive
systemctl is-active clarivo-backend clarivo-agent     # active, active

# 2. Backend reachable publicly
curl -s -o /dev/null -w "%{http_code}\n" https://api.yourdomain.com/    # 200

# 3. Agent registered with LiveKit
journalctl -u clarivo-agent -n 30 --no-pager | grep "registered worker"

# 4. Exactly one agent
pgrep -af "main.py" | wc -l                              # 1

# 5. Network quality to the services that were jittery at home
for h in generativelanguage.googleapis.com api.minimax.io api.deepgram.com; do
  echo -n "$h "; curl -o /dev/null -s -w "connect=%{time_connect}s total=%{time_total}s\n" "https://$h"
done
```

Then make a **test call** and watch the log live:

```bash
journalctl -u clarivo-agent -f
```

Compare against the local baseline:

| Log line | Local (home) | Target (VM) |
|---|---|---|
| `LLMMetrics ttft` | 2.4–13.4s | **< 1.5s** |
| `TTSMetrics ttfb` (greeting) | 0.003s (cached) | 0.003s |
| `TTSMetrics ttfb` (fresh) | 0.6s | **< 0.25s** |
| `Call context:` after SIP join | ~1.9s | **< 0.2s** |
| `flush audio emitter due to slow audio generation` | every reply | **absent** |
| `Request timed out` / `eot prediction timed out` | frequent | **absent** |

Also confirm behaviour, not just speed:
1. **Question-only call** ("timings kya hain?") → must NOT ask name/age, must NOT
   push booking, one short sentence, says "डॉक्टर" in full (never "डॉ.").
2. **Booking call** → confirms the name, asks age, asks reason, returns a real token.
3. **Two calls at once** (needs a 2nd DID) → both answered, each reaching the right
   business. This is the concurrency test that was impossible on Windows.

---

## Operating notes

```bash
# Logs
journalctl -u clarivo-agent -f
journalctl -u clarivo-backend -f

# Restart after a code change (neither hot-reloads)
systemctl restart clarivo-agent      # after editing agent/
systemctl restart clarivo-backend    # after editing backend/
systemctl restart clarivo-agent clarivo-backend   # after editing .env

# CPU steal — if "st" is consistently above ~2-3% the host is oversubscribed and
# will cause audio glitches. Move to a better provider rather than tuning code.
top -bn1 | head -3
```

### Rollback

Nothing here changes the laptop setup. To fall back: stop the VM services
(`systemctl stop clarivo-agent clarivo-backend`), restore `SERVER_URL` to the
ngrok URL in Vobiz, and start the local agent again. Keep only **one** agent running
across both machines.

---

## Cost

| Item | Monthly |
|---|---|
| VM (2 vCPU / 4 GB, Mumbai) | ₹610–2,300 depending on provider |
| Cloudflare Pages (frontend) | ₹0 |
| Caddy / Let's Encrypt TLS | ₹0 |
| Domain (amortised) | ~₹85 |
| **Total added** | **~₹700–2,400** |

For scale: one Starter subscription is ₹4,999/mo, and at 100 tenants × 300 calls the
VM works out to about ₹0.02 per call. The real per-call cost stays the AI + telephony
spend (~₹6–11), not the server.
