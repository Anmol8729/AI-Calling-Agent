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

**Redis IS required now.** This section used to say `REDIS_URL` was dead config. That
stopped being true: `backend/services/limiter.py` uses Redis for rate-limit counters
when `REDIS_URL` is reachable, and `backend/services/events.py` uses it as the
cross-process notification bus. Both degrade instead of failing, so a missing Redis is
easy to overlook — with these consequences:

* Rate limits fall back to per-process memory, so a "10/minute" limit becomes 10 per
  minute *per worker* and resets on every deploy. `check_production_config()` reports
  this as a problem.
* Dashboard notifications are delivered in-process only, so a browser connected to one
  replica never hears an event published by another.

It runs on the same VM (container or `apt install redis-server`), listening on
localhost only, with `--requirepass`. Budget ~50 MB RAM. No separate machine.

**Still not used: Celery and MongoDB.** `celery` and `apscheduler` are in
`requirements.txt` but imported nowhere; reminders are the in-process asyncio task
above. (`README.md` still describes a MongoDB + Celery stack — that is stale; the live
stack is Postgres on Supabase.)

### VM requirements

- **2 vCPU minimum**, 4 GB RAM, 40 GB disk. Measured idle usage is ~250 MB of
  services (agent ~197 MB + backend ~51 MB) plus ~50 MB Redis plus the OS; budget
  **~200 MB per concurrent call** on top. The headroom is what you are paying for.
- **Real (dedicated) vCPU, not burstable/shared.** Voice is soft-real-time: audio is
  encoded and decoded continuously, so CPU steal shows up as audible glitching rather
  than as a slower page. On a shared-CPU plan watch `st` in `top` — consistently above
  ~2-3% means the host is oversubscribed and no amount of tuning will fix the audio.
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

### Pre-flight: is this the right VM?

Run this before anything else. Two of these are not fixable by tuning — you would have
to move to a different VM, and finding out an hour into the deploy is the expensive way
to learn it.

```bash
ssh root@<VM_IP>

uname -m                       # MUST be x86_64. aarch64 = wrong VM, stop here.
lsb_release -ds                # expect Ubuntu 24.04
nproc                          # >= 2
free -m  | awk '/Mem:/{print "RAM  " $2 " MB"}'      # >= 3800
df -h /  | awk 'NR==2{print "disk " $2 " total, " $4 " free"}'   # >= 40G

# Is the CPU shared? Run for ~15s and watch the "st" (steal) column. Anything
# consistently above ~2-3% means the host is oversubscribed and calls will glitch.
vmstat 1 15 | awk 'NR>2{print "steal% " $16}' | sort -n | tail -3

# Latency to the services that made the home connection unusable.
for h in ohyderabad1a.livekit.cloud api.deepgram.com api.minimax.io \
         generativelanguage.googleapis.com api.groq.com; do
  echo -n "$h "
  curl -o /dev/null -s -w "connect=%{time_connect}s\n" "https://$h" 2>/dev/null || echo unreachable
done
```

`aarch64` is a hard stop: `livekit-plugins-noise-cancellation` ships a proprietary
native library with no published arm64 build, and the agent calls
`noise_cancellation.BVCTelephony()`. There is no workaround short of removing noise
cancellation.

### Then harden

```bash
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

Verify both import:

```bash
./.venv/bin/python -c "import backend.app; print('backend OK')"
cd agent && ../agent/.venv/bin/python -c "import numpy, main; print('agent OK, numpy', numpy.__version__)"; cd ..
```

This step used to end with "if numpy is missing, `pip install numpy`" — a workaround for
the real problem, which was that `agent/minimax_tts.py` imports numpy while
`agent/requirements.txt` never listed it. It only worked because livekit-agents and
onnxruntime pull numpy in themselves. It is declared properly now, so a plain
`pip install -r` is enough.

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

# --- Schema: migrations only. The app must not rewrite the schema at boot ---
DB_AUTO_SCHEMA=false                       # run `alembic upgrade head` as a deploy step

# --- LLM chain. Do NOT pin a single provider here ---
# This file used to say AGENT_LLM_PROVIDER=gemini. That pins ONE model and skips the
# FallbackAdapter, so when it rate-limits the caller hears silence with nothing behind
# it — observed on a free Gemini key, which allows 5 REQUESTS/minute while a call
# spends 1-2 per turn (dry after ~3 turns). check_production_config now refuses to
# boot with it set, so following the old advice would fail at startup.
# Groq first: ~0.5s to first token vs Gemini's 1.3-3s, and its quota is separate.
AGENT_LLM_ORDER=groq,gemini,minimax
AGENT_PREEMPTIVE=0                         # 1 caused "Request timed out" + 13s replies

# --- Email. Without this, password resets and email verification do NOTHING ---
# (the link is only written to the server log). See section 11 for the DNS records.
SMTP_HOST=smtp-relay.brevo.com             # or your provider
SMTP_PORT=587                              # 587 = STARTTLS · 465 = implicit TLS
SMTP_USER=<provider login>
SMTP_PASSWORD=<provider SMTP key>
SMTP_FROM=Clarivo <no-reply@yourdomain.com># must be an address the provider verified
SMTP_TLS=true

# --- Keep the tuning that was verified on real calls ---
MINIMAX_TTS_MODEL=speech-2.6-turbo
MINIMAX_TTS_EMOTION=
MINIMAX_TTS_SAMPLE_RATE=8000               # PSTN is 8kHz anyway; lower ttfb
AGENT_TTS_CACHE=1                          # greeting served from disk in ~3ms
```

`AGENT_INTERNAL_SECRET` must be set to its own value. It used to fall back to
`JWT_SECRET`; that fallback is gone from both the backend and the agent, because it
reused the session-signing key as an API credential — leak it anywhere in the call
path and an attacker could mint tokens for any user. With it unset, every booking
returns 401.

Prove the mailer works before a customer needs it:

```bash
.venv/bin/python -m backend.services.email you@example.com
```

Lock the file down:

```bash
chmod 600 ~/AI-Calling-Agent/.env
```

Also rotate, per the pre-launch checklist: the **WhatsApp access token** and the old
**Supabase DB password**, both of which are still in git history.

### Apply migrations (required, now that `DB_AUTO_SCHEMA=false`)

With auto-schema off the app no longer creates or alters anything at boot, so this is
the only thing that builds the schema. It has to run after `.env` exists, because
Alembic reads the database URL from it:

```bash
cd ~/AI-Calling-Agent
./.venv/bin/python -m alembic current        # where the database is now
./.venv/bin/python -m alembic upgrade head   # apply anything outstanding
./.venv/bin/python -m alembic check          # expect "No new upgrade operations detected"
```

For this first deployment the existing Supabase database is already at head, so
`upgrade` is a no-op — but run it anyway, and run it on **every** deploy that ships a
new migration. Skipping it is silent: the app starts fine and then fails on the first
query that touches a missing column.

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

## 10. Point Supabase Auth at the new domain (Google sign-in breaks without this)

Easy to miss, because nothing in this repo needs changing. The frontend asks Supabase
to send the user back to `${window.location.origin}/auth/callback`
(`frontend/src/lib/supabase.js`), so on production that becomes
`https://app.yourdomain.com/auth/callback`. Supabase refuses any `redirectTo` that is
not on its allowlist, and the failure surfaces as a generic "redirect not allowed"
after the user has already picked their Google account.

In the Supabase dashboard → **Authentication → URL Configuration**:

| Field | Value |
|---|---|
| Site URL | `https://app.yourdomain.com` |
| Redirect URLs | add `https://app.yourdomain.com/**` (keep `http://localhost:3000/**` for local dev) |

**Google Cloud Console** needs no change for the domain: the authorised redirect URI
is Supabase's own callback (`https://<project-ref>.supabase.co/auth/v1/callback`), not
ours. Only touch it if the Supabase project changes.

Verify by signing in with Google on the deployed site — a new row should appear in
`public.users` with `supabase_user_id` set, and an `auth.login` audit row with
`{"provider": "google"}`.

---

## 11. Email DNS (or resets land in spam)

SMTP credentials alone are not enough. Mail sent as `@yourdomain.com` needs the domain
to authorise the provider, or it is rejected or filed as spam — and nothing logs an
error, because the send itself succeeded.

Your provider will give you exact values; the shape is:

| Record | Name | Purpose |
|---|---|---|
| TXT | `@` | **SPF** — lists who may send as your domain, e.g. `v=spf1 include:spf.brevo.com ~all` |
| TXT | provider-specified (e.g. `mail._domainkey`) | **DKIM** — signs each message so it cannot be forged |
| TXT | `_dmarc` | **DMARC** — what to do with failures, e.g. `v=DMARC1; p=none; rua=mailto:you@yourdomain.com` |

Start DMARC at `p=none` (monitor only). Moving to `p=reject` before SPF and DKIM both
pass will silently drop your own password-reset emails.

Then verify end to end, not just the SMTP handshake:

```bash
.venv/bin/python -m backend.services.email you@yourdomain.com   # 1. can we send at all
curl -X POST https://api.yourdomain.com/api/auth/forgot-password \
     -H 'Content-Type: application/json' \
     -d '{"email":"you@yourdomain.com"}'                        # 2. does the real flow send
```

Step 2 always answers "if that email is registered, a reset link has been sent" — that
is deliberate anti-enumeration, so it is NOT evidence of success. Check the inbox, and
check it did not land in spam. Then click the link and confirm it opens
`https://app.yourdomain.com/reset-password` and the password actually changes.

---

## 12. Verify (in this order)

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
