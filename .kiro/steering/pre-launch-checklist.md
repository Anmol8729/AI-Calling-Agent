# Clarivo — Pre-Client-Launch Checklist

> **Security work has its own tracker: `docs/SECURITY-REMEDIATION.md`.**
> Read it before touching auth, the agent's backend endpoints, or the websockets.
> Closed and verified there (do NOT re-open): privilege escalation via signup ·
> weak-password policy · XML injection on the inbound webhook · `.dockerignore`
> secrets-in-image · security headers · `/health` · prod config fail-fast ·
> **C2** agent per-call token scoping · **C3** session revocation ·
> **C1** removal of the unauthenticated `/media-stream` pipeline.
> Still open there: **C4** RBAC (waiting on the teammate's Staff Panel), **C5**
> rotate `JWT_SECRET` (owner, doing last), **C6** Redis/compose, and H2-H12.

Gate to run **before sending the product to any real client**. Everything below was
established by testing against the live system, not assumed. Items marked ✅ are
verified working — do not re-debug them. Items marked ⛔ / ⏳ are still open.

---

## ⛔ BLOCKERS — must be done before a client touches this

### 1. Credential hygiene (verified: nothing has leaked to git)
`.env.example` **is tracked by git** (`.env` is correctly ignored), and it did contain
REAL secrets — a live Meta WhatsApp token and an old Supabase DB password — but only in
the **uncommitted working tree**. Scanning every commit (`git log --all -p`) confirmed
**no secret was ever committed**, so nothing is exposed on any remote.

Still do these:
- **Rotate the Meta WhatsApp access token** as a precaution — it sat one `git add -A`
  away from being published.
- Set a strong **JWT_SECRET** (see next section):
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- Never put real values in `.env.example` again — it is a tracked template.

Before any push, re-run a secret scan over what would actually be committed:
`git ls-files --cached --others --exclude-standard` then grep those files for
`sk-api|gsk_|EAAU|AIza|postgresql://.*:.*@`.

### 2. Set the production-critical env values
| Key | Why it matters |
|---|---|
| `JWT_SECRET` | Empty ⇒ insecure built-in default ⇒ anyone can mint valid session tokens. Also used as the fallback for the agent's internal secret. |
| `APP_BASE_URL` | Password-reset / invite links are built from it. Wrong value ⇒ emailed links open a dead page. |
| `CORS_ORIGINS` | Must list the exact deployed dashboard origin. Wildcard `*` is NOT allowed (the API uses `allow_credentials=True`). |
| `SERVER_URL` | Vobiz webhook target. Currently an **ngrok** URL — must become a stable HTTPS domain. |
| `VOBIZ_TRUNK_GROUP_ID` | `a120869b-9cd5-4e34-a91f-b7a6a6aa18d8` (verified). Without it the one-click "Get a number" button stays hidden. |

### 3. Deploy the voice agent on Linux (biggest single win)
Running the agent on local Windows is the root cause of three separate problems.
Moving it to a cloud Linux VM near the LiveKit India region fixes all three at once:

- **Concurrency** — needed before two clients can be on calls simultaneously. Never tested yet.
- **Stability** — LiveKit's native layer panics on Windows at call teardown
  (`malformed serialized RtcError` in `webrtc-sys/src/rtc_error.rs`), killing the worker.
  Currently worked around with a restart wrapper + `AGENT_RECYCLE_AFTER_CALL`.
- **Latency** — ~1.5s per turn is just audio crossing a home internet link twice.
  On Linux set `AGENT_RECYCLE_AFTER_CALL=0` so one warm worker serves many calls.

### 4. Test with 2 clients end-to-end
Never done. Needs a 2nd Vobiz DID. Register a 2nd clinic → Setup (industry, KB, voice)
→ claim/connect its DID → call **both** numbers and confirm each reaches the right
business (check the agent log line `Call context: did=... clinic=... business=...`).

---

## ✅ VERIFIED WORKING — don't re-investigate

- **Multi-tenant DID routing.** The agent now waits for the SIP participant before
  reading attributes, so the dialed number actually arrives
  (`sip.trunkPhoneNumber` → e.g. `+918065480571`). It resolves the clinic from
  `phone_numbers`, not from the single-clinic fallback. Confirmed end-to-end.
- **Data isolation.** Every query is scoped by `clinic_id`; one client cannot see another's data.
- **Supabase DB** (Mumbai / `ap-south-1` pooler) connected, schema auto-created on startup.
- **Dashboard ↔ backend.** All ~40 frontend calls map to real backend routes — no path/method
  mismatches. Auth, JWT injection and the 401→/login redirect work.
- **AI call flow.** Answers in pure Hindi from the knowledge base, confirms the caller's
  name, collects age + reason, books (token or time mode), saves to the dashboard, and
  hangs up via `end_call`. Age/gender persist onto the patient record.
- **One-click number provisioning (Phase 1).** `POST /api/phone-numbers/provision`
  claims a free number from the Vobiz inventory, assigns it to the trunk (→ LiveKit),
  and maps it to the clinic. It only claims — it never buys, so no accidental spend.
- **Build health.** `npm run build` → 0 errors; `npm run lint` → 0 problems.

---

## ⏳ OPEN / NICE-TO-HAVE

- **Phase 2 auto-buy.** Blocked: Vobiz has not given the number **search** and **buy**
  endpoints (only `PATCH /numbers/{number}/assign` is known). When they do, add guardrails
  first — numbers cost ₹100 setup + ₹500/month, so auto-purchase = auto-spend. Gate on paid
  plan, cap per clinic, cap per month.
- **Billing.** Plan prices are `null`, so every plan shows "Request upgrade" and the Razorpay
  checkout path is unreachable. Set prices + keys to charge clients.
- **Call quota.** `ENFORCE_CALL_QUOTA=false`. Turn on so clients stay within their plan.
- **Bundle size.** Single 764 kB JS chunk; code-splitting would help first load.
- **Remaining dependency advisory.** One react-router `RSC Mode CSRF` advisory needs a
  breaking v8 bump. Deliberately skipped — this is a client-side Vite SPA with no RSC/SSR,
  so it does not apply. Other audit findings are build-time only.

---

## GOTCHAS — hard-won, don't relearn these

- **LLM choice matters.** The chain is a `FallbackAdapter` and its order is set by
  `AGENT_LLM_ORDER` (default `gemini,groq,minimax`). `AGENT_LLM_PROVIDER` pins a single
  provider with no failover, for A/B testing.
  - **The Gemini key is FREE TIER: 5 requests/minute.** Error names it outright:
    `generate_content_free_tier_requests, limit: 5, model: gemini-3.6-flash`. A call
    uses 1–2 requests per turn, so it runs dry after ~3 turns and the caller hears
    silence. Enable billing, or set `AGENT_LLM_ORDER=groq,gemini,minimax`.
  - **Both `-latest` aliases share ONE project quota**, so two Gemini entries was fake
    redundancy that also burned an `attempt_timeout` of silence. `GEMINI_FALLBACK_MODEL`
    is empty by default now; only set it on a paid tier.
  - **Groq needed a code fix to work as a fallback at all.** LiveKit copies Gemini's
    `extra_content` (thought signatures) into the *shared* chat context and re-sends it to
    every OpenAI-compatible provider; Groq rejects it with
    `400 'messages.N' : property 'extra_content' is unsupported`. So Groq worked only
    until the first assistant tool call, then failed every turn. `_StrictSchemaLLM` in
    `agent/main.py` strips `.extra` on a copy (leaving Gemini's own signatures intact).
    Groq is also the fastest option: ~0.5s to first token vs Gemini's 1.3–3s.
  - Groq free tier ≈ **12k tokens/min**; this agent sends ~3.3k per turn ⇒ 429s after
    3–4 turns. `AGENT_PREEMPTIVE=0` halves per-turn requests and helps on any free tier.
  - Use a **`-latest`** Gemini alias. Pinned ids (`gemini-2.5-flash`, `-flash-lite`) return
    **404 for new keys**, and `gemini-flash-lite-latest` has been seen both hanging
    server-side and returning `503 experiencing high demand`.
  - MiniMax-Text-01 writes tool calls as text instead of calling them; MiniMax-M3 leaks
    `<think>`. It stays LAST, but it stays *in* the chain — its quota is separate, so it is
    the only thing left when Gemini and Groq are both rate-limited at once.
  - **Only ONE agent worker should run.** Two registered workers make LiveKit split calls
    between them at random, so half your test calls hit stale code.
- **TTS loudness.** Gain is applied after synthesis via a **soft-knee limiter**. A plain
  multiply clipped the peaks and sounded "cut"/computerized. Tune `MINIMAX_TTS_GAIN`
  (2.0 default; ~3.0 louder, ~1.5 softer). Keep `MINIMAX_TTS_VOL=1.0` for headroom.
- **"AI not responding" is usually not a code bug.** Check the agent log first:
  429 (quota), `Request timed out` (network or a hanging model), or every reply being
  interrupted because the caller talks continuously (`ttfb=-1.000`).
- **Booking is intent-gated.** The AI must not push appointments; it only starts intake
  when the caller asks. Enforced in 4 prompt sections — keep them consistent if editing.
- **Vobiz has two credential sets.** SIP trunk username/password (calls) vs REST
  **Auth ID / Auth Token** (number provisioning, HTTP Basic). They are not interchangeable.
- **Vobiz does not auto-route new numbers.** Each DID must be assigned to the trunk;
  one trunk serves all numbers.

---

## HOW TO RUN / VERIFY

```powershell
# Backend (no --reload). --host 0.0.0.0 is REQUIRED: ngrok resolves "localhost"
# to IPv6 [::1], which uvicorn on 127.0.0.1 never answers -> calls go unreachable.
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000

# Voice agent (cwd = agent). Wrapper restarts it after the Windows teardown panic.
# Run only ONE — two workers make LiveKit split calls between them.
while ($true) { & '.venv\Scripts\python.exe' main.py dev; Start-Sleep -Seconds 2 }

# Dashboard → http://127.0.0.1:3000  (NOT localhost)
npm run dev -- --host 127.0.0.1 --port 3000

# ngrok — pin the IP for the same IPv6 reason. Static domain, so the URL is stable.
ngrok http 127.0.0.1:8000
```

Checks: `npm run build` + `npm run lint` (expect 0 / 0) ·
`python -c "import backend.app"` · `pytest backend/tests` (expect 11 passed) ·
backend `GET /health` should return 200 with `"database": "ok"` (plain `GET /`
never touches the DB, so it can look healthy while the DB is down) ·
agent log should show `registered worker` with `agent_name: clarivo-inbound`.

Restart the backend after backend changes and the agent after agent changes —
neither hot-reloads. Delete any temporary `_*.py` diagnostic scripts afterwards.
