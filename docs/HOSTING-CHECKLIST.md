# Hosting Purchase Checklist — Clarivo

Keep this open while talking to a hosting salesperson. Every requirement below is
traced to a specific line in this repo, so you can answer "why" if pushed.

Sales reps assume you are hosting a **website**. You are not. Correcting that
assumption early prevents ~80% of wrong recommendations.

---

## 1. Open with this line

> "I need a plain **unmanaged KVM VPS** with root SSH — to run two Python
> background services. It's not a website: no PHP, no WordPress, no cPanel.
> It's a real-time voice application, so consistent CPU and low network latency
> matter more than disk space."

If you only say "VPS", you will be shown Managed/cPanel plans that cost ~3x more
than what you need.

---

## 2. Hard requirements (no compromise)

| Requirement | Value | Why — traced to this repo |
|---|---|---|
| Virtualization | **KVM** (not OpenVZ / container) | Services run under `systemd`; container VPS often can't run it properly |
| Architecture | **x86_64 / AMD64** | `agent/main.py:920` uses `noise_cancellation.BVCTelephony()`; `livekit-plugins-noise-cancellation` has **no arm64 build** |
| OS | **Ubuntu 24.04 LTS** (22.04 acceptable) | Needs Python **3.12** — see gotcha in §7 |
| Control panel | **None** | Caddy needs ports 80/443 for TLS; cPanel/Plesk occupy them |
| vCPU | **2 minimum** | Silero VAD runs every 32 ms; delayed CPU = choppy audio |
| RAM | **4 GB** | Measured: agent ~197 MB + backend ~51 MB idle, **+~200 MB per concurrent call** |
| Disk | **40 GB is plenty** | Code + venvs + TTS disk cache (capped at 200 MB) |
| Root SSH | From day 1 | Required to install Python, Caddy, systemd units |
| Region | **Mumbai** (or Bangalore/Hyderabad) | LiveKit region is `ohyderabad1a`; Supabase is `ap-south-1` Mumbai |
| Inbound ports | **22, 80, 443 only** | No SIP/media on the VM — see §6 |

---

## 3. Ask them these 12 questions

```
1.  Is it KVM or OpenVZ/container virtualization?
2.  Is Ubuntu 24.04 LTS available? (or only 20.04?)
3.  Is it x86_64 or ARM?
4.  Are the vCPUs dedicated or shared/burst? What is the CPU steal policy?
5.  Which datacenter exactly — Mumbai?
6.  Do I get root SSH from day 1?
7.  Are any ports blocked? I will run my own web server on 80/443.
8.  Is outbound bandwidth throttled or subject to a fair-use cap?
9.  Does a control panel come pre-installed? Can I remove it?
10. What is the RENEWAL price, not the promo price?
11. What is the refund / trial period?
12. What do snapshots or backups cost extra?
```

Questions **1** and **10** save the most money.

---

## 4. Red flags — stop if you hear these

| They say | Problem |
|---|---|
| "OpenVZ" / "container-based" | `systemd` won't run reliably |
| "cPanel is included" (can't remove) | Port conflict with Caddy → no TLS cert |
| "Ubuntu 20.04 is our latest" | EOL OS, ships Python 3.8 |
| "ARM / Ampere is better value" | noise-cancellation library will not load |
| "Unlimited bandwidth" | Usually hides a fair-use throttle |
| "Shared/burst CPU" with no floor | Audio glitches during calls |
| No refund period | You cannot test before committing |

---

## 5. Upsells to decline

Domain · Managed support · cPanel / Plesk / CyberPanel · SSL certificate
(Caddy gets one free from Let's Encrypt) · Website builder · Email hosting ·
CDN · Malware scanner · anything "WordPress optimized" · extra IPv4

---

## 6. What you do NOT need — don't pay for it

| Offered | Your actual need |
|---|---|
| Large disk | 40 GB. Nothing large is stored on the VM |
| High bandwidth | ~8 MB per call → **1 TB is plenty** (~240 GB/mo at 100 tenants) |
| MySQL / managed database | Postgres already lives on Supabase (Mumbai) |
| Email accounts | Transactional email goes out via SMTP (`backend/services/email.py`) |
| SIP / RTP media ports | SIP goes Vobiz → LiveKit Cloud. The VM never terminates SIP |
| Redis add-on | **Not used.** `redis`, `celery`, `apscheduler` sit in `requirements.txt` but are never imported. Rate limiting is in-memory (`backend/services/limiter.py`); reminders are an in-process asyncio task |
| Load balancer (for now) | One box until you outgrow it |

---

## 7. Technical gotchas to state up front

- **Python 3.12, not 3.13.** `audioop` was removed in 3.13; the TTS gain path
  silently falls back and loses audio.
- **Timezone must be `Asia/Kolkata`.** `appointment_at` is stored as naive local
  wall-time and compared against `datetime.now()` (`backend/jobs/reminder_worker.py`).
- **Backend must run `--workers 1`.** The reminder worker is started in-process by
  the app lifespan (`backend/app.py:37`, `asyncio.create_task(reminder_loop())`).
  Multiple workers = duplicate WhatsApp reminders.
- **WebSockets must pass through.** `backend/websocket/handler.py` is mounted, so no
  proxy that kills long-lived connections or buffers them.
- **Unrestricted outbound HTTPS (443)** to LiveKit, Google (Gemini), MiniMax,
  Deepgram, Supabase, Meta WhatsApp, Razorpay.

---

## 8. Domain / TLS / webhook

You will need a domain or subdomain pointing at the VM's IP, because:

- Caddy issues the Let's Encrypt certificate over ports **80 and 443**
- `SERVER_URL` is Vobiz's webhook target and is currently an **ngrok URL** —
  it must become a stable HTTPS domain before launch
- `CORS_ORIGINS` must list the exact dashboard origin (wildcard `*` is rejected
  because the API sets `allow_credentials=True` in `backend/app.py`)

Buy the domain from a registrar (Cloudflare/Namecheap), not from the hosting rep.

---

## 9. Data residency — ask this, it's a business requirement

The product stores patient **name, age, phone, and reason for visit**
(`backend/db/schema.sql`). That is health-adjacent personal data.

Ask: **"Will all data and backups stay inside India?"**

Keep it in-region for a defensible DPDP Act position. Your clinic customers will
eventually ask you the same question, so get the answer in writing.

---

## 10. Shortlist as of this writing

| Provider | Plan | Price | Note |
|---|---|---|---|
| Hostinger | KVM 2 — 2 vCPU / 8 GB, Mumbai | ~₹610/mo | Recommended. Check renewal price |
| Vultr | 2 vCPU / 4 GB, Mumbai | hourly (~₹3/day) | Best for a throwaway test first |
| MilesWeb | — | — | Rejected: Ubuntu 24.04 not offered (newest 20.04, EOL); unmanaged 1 vCPU ₹949 |
| Contabo | — | — | Rejected: oversubscription risk → audio glitches |
| Oracle Always Free | 2 OCPU / 12 GB Hyderabad | ₹0 | Rejected: **ARM only** → noise-cancellation won't build |

Prices move — reconfirm before buying, and always ask for the **renewal** figure.

---

Full server setup steps: `docs/DEPLOYMENT.md`
Pre-launch gate: the pre-launch checklist in `.kiro/steering/`
