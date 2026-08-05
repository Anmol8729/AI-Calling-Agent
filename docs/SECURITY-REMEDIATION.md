# Clarivo — Security Remediation Tracker

Living tracker for the production-readiness / security audit. Every item was
found by inspecting real code and, where marked *verified*, proved with a live
test against the running system. **Do not delete an item when it is done — mark
it DONE so we never re-debug it.**

Legend: `DONE` fixed + verified · `IN PROGRESS` · `TODO` · `BLOCKED` waiting on
something external · `WONTFIX` deliberate, with reason.

---

## Owner decisions on record (2026-08-05)

| Decision | Detail |
|---|---|
| `JWT_SECRET` rotation | Owner will rotate **last**, after the code work. Currently only 19 chars. Rotating logs everyone out — do it in a maintenance window. |
| C4 (RBAC redesign) | **Deferred** until the teammate pushes the Staff Panel. It changes `users` schema + role names, so it must not land first. |
| Work order | C2 → C3 → C1. |

---

## CRITICAL

### C1 — Unauthenticated `/media-stream` WebSocket
**Status: DONE — exploit reproduced, then removed and re-verified**
`backend/websocket/handler.py` (rewritten) · `backend/integrations/minimax/` (deleted)

The owner asked me to confirm it was genuinely dead before removing, so I probed
the running server rather than reasoning about it. **It was worse than the audit
described — the impact was live, not theoretical:**

* an anonymous WebSocket handshake was **accepted with no credentials**,
* `?destination=` selected a **real paying tenant** (Dk Dental Clinic),
* the server **streamed synthesised audio back** (`event=playAudio`), i.e. it
  really did spend MiniMax TTS + LLM credits for an anonymous caller,
* and it **wrote a `call_logs` row into that tenant** — so anyone could inject
  fake calls into a customer's dashboard and burn their monthly quota.

Proof it was dead for real traffic (two independent lines):
1. `call_logs` sat at **zero rows** across many verified live calls, even though
   this handler writes a row on its `start` event (my probe confirmed it does).
   So it never received a real call.
2. The agent carries its own TTS (`agent/minimax_tts.py`) and STT
   (`deepgram.STT`); the backend's MiniMax modules had **no other importer**.

Removed the route and the three modules only it used. `/ws/notifications` was kept
and hardened (a scoped agent token can no longer open it).

Re-verified after removal: `/media-stream` refused (403), notifications still
rejects anonymous clients, notifications still works with a valid session, an
agent token is refused, and no `call_logs` row is created. 5/5.

`POST /api/calls/twiml/inbound` was deliberately **left reachable** — the Vobiz
trunk still lists it as its webhook and changing it carries risk with no benefit,
since the evidence says the provider never drives calls through it. It now logs at
WARNING when hit, so if that assumption is ever wrong we find out from the logs.

### C2 — Agent endpoints trust `clinic_id` from the request body
**Status: DONE — verified**
`backend/routes/calls.py`, `backend/services/call_tokens.py`, `agent/main.py`

One global shared secret guarded 9 endpoints, and each took `clinic_id` straight
from the JSON body. Anyone holding that secret could read any tenant's
`system_prompt` + `knowledge_base` (their business IP) and write bookings and
contacts into any tenant. `agent-call-transcript` / `agent-call-end` accepted any
`call_id` with no ownership check at all (IDOR).

Fix: `/agent-context` is now the only shared-secret endpoint. It resolves the
clinic from the **dialed DID only**, then returns a short-lived token bound to
`(clinic_id, call_id)`. Every other agent endpoint requires that token and reads
the clinic from its claims — the body value is ignored. Transcript/end additionally
assert the `call_id` matches the token.

Also hardened along the way: the shared secret is compared with
`secrets.compare_digest` (a plain `==` leaks it byte-by-byte to timing analysis),
and its fallback to `JWT_SECRET` is gone — that fallback meant a deployment which
forgot `AGENT_INTERNAL_SECRET` silently reused the session-signing key as an API
credential. Call tokens are signed with a key *derived from*
`AGENT_INTERNAL_SECRET`, so the agent's trust domain is cryptographically separate
from user sessions.

On the agent side the token is held in a `contextvars.ContextVar`, not a module
global: with `AGENT_RECYCLE_AFTER_CALL=0` (the Linux setting) one worker serves
several concurrent calls, and a global would let call B overwrite call A's token
and write into the wrong tenant.

Verified live, 11/11: shared secret refused on non-bootstrap endpoints ·
anonymous refused · bootstrap issues a token · a body `clinic_id` cannot override
DID resolution · bad secret refused · token works for its own call · cross-call
transcript write **403** · cross-call hangup **403** · tampered token refused ·
a user session token refused on agent endpoints.

### C3 — No session revocation
**Status: DONE — verified**
`backend/models/__init__.py`, `backend/services/auth_service.py`, `backend/routes/auth.py`

7-day access token with no `jti`, no refresh rotation, no server-side logout.
Password change/reset left stolen tokens valid; a suspended user kept access.

Fix: `users.token_version`, `users.password_changed_at`, `users.is_active`.
Tokens carry `ver`; `get_current_user` rejects a stale `ver` or an inactive user.
Password change/reset and the new `POST /auth/logout-all-devices` bump
`token_version`, which invalidates every existing token instantly.

Details worth remembering:
* Tokens issued before this change carry no `ver`, read as `0`, and match the
  column default — so the upgrade did **not** log everyone out.
* `change-password` returns a **replacement token**, because bumping the version
  also kills the caller's own session. `Account.jsx` adopts it via a new
  `authStore.setToken`, otherwise the next request would 401 straight to /login.
* `logout()` is now async and calls `logout-all-devices` first, so a token copied
  off the machine stops working too. `Sidebar.handleLogout` awaits it.
* Session length dropped from a hardcoded **7 days to 24 hours**, now settable
  with `ACCESS_TOKEN_EXPIRE_MINUTES`. Revocation makes this a ceiling rather than
  the only control; refresh-token rotation is the follow-up that would remove the
  re-login friction entirely.
* `password_hash` is now stripped from the request-scoped user dict, so a future
  handler cannot leak it by returning `current_user` wholesale (was M8).
* Suspended accounts are blocked **and** cannot log back in, with the same generic
  message as a wrong password so suspension isn't confirmable from outside.
* Reset also burns any other unused reset tokens, so an older emailed link cannot
  be replayed to retake the account.

Verified live, 10/10, on a throwaway user that was hard-deleted afterwards:
token works → `logout-all-devices` revokes it (401) → re-login works → password
change kills the old token (401) and the replacement works (200) → weak new
password refused (422) → suspension blocks the valid token (403) and blocks login.

Added alongside (was M5): composite indexes `call_logs(clinic_id, created_at DESC)`
and `appointments(clinic_id, appointment_at)`, which are the shapes every dashboard
query actually uses.

### C4 — RBAC hierarchy does not exist
**Status: BLOCKED** — waiting on the teammate's Staff Panel push (owner's call).

`require_roles` is defined at `backend/routes/auth.py` and **never called once**.
Roles in the DB are `doctor` / `admin` / `receptionist`, not
Super Admin → Company Admin → Staff. No permissions model, no staff endpoints, no
invite flow, and no `is_active` on tenants, so "suspend a company" is impossible.

Planned: `roles`, `permissions`, `role_permissions`, `user_permissions`,
`tenants.status`, a real `platform_admins` table replacing the email allowlist,
then a `require_permission(...)` dependency across all 57 endpoints.

### C5 — `JWT_SECRET` is only 19 characters
**Status: BLOCKED** — owner rotating last, on purpose.
Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
The startup guard already warns, and will refuse to boot once `ENV=production`.

### C6 — Redis published with no password; source bind-mounted
**Status: DONE — config verified; image build NOT yet verified (Docker daemon was off)**
`docker-compose.yml`, `Dockerfile`, `.env.example`

Three problems, all fixed:

1. **Redis was published on `6379:6379` with no password.** On a host with a public
   IP that is an open Redis — remote config rewrite, the standard ransomware
   vector. It only ever needed to be reachable by the API container. Now: **no
   `ports:` key at all** (internal network only), `--requirepass` required, plus
   `FLUSHALL` / `FLUSHDB` / `CONFIG` renamed away as defence in depth.
2. **`volumes: [".:/app"]`** bind-mounted the repo over the image, shipping the real
   `.env` into the running container and meaning the code that ran was whatever sat
   on the host rather than what was built. Removed — the image is the artefact.
3. **`REDIS_PASSWORD` is mandatory.** `${REDIS_PASSWORD:?...}` makes compose refuse
   to start rather than silently coming up open. Verified: without it,
   `docker compose config` errors with
   `required variable REDIS_PASSWORD is missing a value: set REDIS_PASSWORD in .env`.

Bundled the container hardening (part of H6) because a locked-down compose pointing
at a root container is only half a fix:
* **Multi-stage build** — `build-essential` (a full C toolchain) now exists only in
  the builder and never ships.
* **Runs as an unprivileged user** (`clarivo`, uid 1001) instead of root, with the
  source owned by root and read-only to the app, so the process cannot rewrite its
  own code.
* **`no-new-privileges`** on both services, memory limits, and log rotation.
* **Healthchecks** in both the image and compose, hitting `/health` (which
  round-trips a DB query) so a container that lost its database reports unhealthy
  instead of quietly serving errors. `depends_on` now waits on
  `condition: service_healthy`.

**Note: Redis is currently used by nothing.** `REDIS_URL` is read in `settings.py`
and referenced nowhere else, and there is no Celery usage. It is kept because H4
(rate limiting off in-memory storage) and H3 (event bus to pub/sub) both need it.
Until then the service can be commented out entirely.

Verified: compose config renders valid · `redis` has **no** `ports` key · no bind
mount remains · `requirepass` present · `no-new-privileges` on both services ·
the healthcheck one-liner exits 0 against the live backend · `.dockerignore` still
excludes `.env` / `.git` / `.venv` and blocks none of the files the build needs.

**Not verified:** `docker build`. The Docker daemon was not running on the dev
machine, so the image was never actually built. `docker compose config` is
client-side only. Run `docker build -t clarivo-api .` once Docker Desktop is up.

**Owner action:** add `REDIS_PASSWORD` to `.env`
(`python -c "import secrets; print(secrets.token_urlsafe(32))"`). Compose will not
start without it.

---

## Fixed earlier in this audit (all verified live)

| ID | Issue | Proof |
|---|---|---|
| — | Privilege escalation: signup accepted `role: "admin"` / `"superadmin"` | 3/3 payloads → 422, no rows created. Role is decided server-side now. |
| — | Weak passwords (`123456`, `password`) accepted | 3/3 → 422. 10 chars, 3 character classes, common-password blocklist, on register + change + reset. |
| — | XML injection on the public inbound webhook (injected `<Dial>` / `<Say>` rendered as real verbs — toll fraud) | Attack payload returns clean XML; allow-listed at input **and** escaped at output. |
| — | `.dockerignore` missing → `COPY . .` baked `.env` + full `.git` into every image | Created. |
| — | No security headers at all | 7 verified live: CSP, HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy, COOP/CORP, Permissions-Policy, plus `no-store` on `/api/*`. |
| — | No health check (`/` never touched the DB) | `GET /health` → 200 with `database: ok`; 503 when the DB is down. |
| — | Nothing stopped a prod boot with a default secret | `enforce_production_config()` aborts startup on `ENV=production` for a weak `JWT_SECRET`, wildcard/localhost CORS, non-HTTPS `APP_BASE_URL`, or `AGENT_INTERNAL_SECRET == JWT_SECRET`. |

---

## HIGH

### H4 — Rate limiting and brute-force protection
**Status: DONE — verified 9/9**
`services/limiter.py`, `services/login_guard.py`, `routes/auth.py`, `models`, `db.py`

Two separate problems. The rate limiter stored counters **in process memory**, so a
"10/minute" limit was really 10 per minute *per worker* and reset on every deploy.
And there was no per-ACCOUNT control at all, so credential stuffing from a pool of
IPs never tripped anything.

* Limiter now uses **Redis** when `REDIS_URL` is reachable (shared across
  processes), probed at boot. If Redis is down it degrades to memory and logs an
  error rather than refusing to boot — verified working both ways.
* **Per-account lockout** in the database (`users.failed_login_attempts`,
  `locked_until`, `last_login_at`), so it survives restarts and ignores IPs.
  Escalating (15m → 30m → 60m, capped at 120m) rather than permanent, because a
  permanent lock would let anyone who knows an email deny that user access forever.
* A **password reset clears the lockout** — the lockout message tells users to reset
  their password to get back in, so that had to actually work.
* Two timing leaks closed: an unknown email now runs a bcrypt comparison against a
  dummy hash, and a locked account still verifies the password before rejecting.
  Otherwise response timing revealed which addresses exist and which are locked,
  despite the identical error text.

Verified live on a throwaway account (deleted afterwards): 5 wrong passwords from 5
**different** `X-Forwarded-For` addresses still locked the account · lockout returns
429 · the **correct** password is refused while locked · clearing the lockout
restores access · a successful sign-in resets the counter and stamps `last_login_at`.

### H8 — Database TLS was encrypted but unverified
**Status: DONE — verified, with a control test**
`services/db.py`, `backend/certs/supabase-prod-ca-2021.crt`, `settings.py`

The code set `verify_mode = CERT_NONE`, with a comment claiming Supabase's chain has
a self-signed root. **I tested the claim against the live database and it is true** —
verification via both the OS trust store and certifi fails with
`self-signed certificate in certificate chain`. The server presents
`CN=*.pooler.supabase.com` issued by `Supabase Intermediate 2021 CA`, chaining to a
self-signed `Supabase Root 2021 CA` that is in no public trust store.

But disabling verification meant the link was encrypted and **authenticated
nothing**: anything able to intercept it could present its own certificate and read
or rewrite every query, including credentials and patient data.

Fix: pin Supabase's own root (bundled at `backend/certs/`, sha256
`700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7`, digest checked
at load so a substituted file is refused). `DB_SSL_ROOT_CERT` overrides it for
rotation or a different provider. Full verification — chain **and** hostname — is
now on, confirmed by a live `SELECT 1`; a control attempt with the wrong CA is
correctly rejected, which proves verification is genuinely enforced rather than
silently skipped. `DB_TLS_VERIFIED` is surfaced to the startup config guard.

Cross-check the digest against the certificate from your own dashboard
(Settings → Database → SSL Configuration) before trusting the bundled copy.

### H9 — Number provisioning had no plan gate and no cap
**Status: DONE — verified 9/9**
`routes/phone_numbers.py`, `services/plans.py`, `models`, `db.py`

`POST /phone-numbers/provision` could be called in a loop by **any** account,
including a free trial. Each DID costs roughly ₹100 setup plus ₹500/month and draws
from a finite shared pool, so this was unbounded spend. Now gated on
`plans.included_numbers` (Trial 1, Starter 2, Growth 5, Scale 10) with a per-tenant
`tenants.number_limit` override, checked **before** the provider is contacted.
`GET /provision-info` reports `numbers_used` / `numbers_included` / `can_provision`
on every path, so the dashboard can disable the button with a reason instead of
letting a client click into a 403.

**Found and fixed while in this file — cross-tenant number hijacking.** The
uniqueness check compared the raw string, but inbound routing resolves a dialed
number by trying format variants (`_did_variants`). So clinic B could connect
`918065480571` while clinic A held `+918065480571` — two distinct rows past the
unique constraint — and whichever variant matched first would win, capturing
another tenant's calls. Claims are now compared on digits, making a number
claimable exactly once platform-wide. Verified: clinic B's attempt is refused 400.

Still open: there is no proof of **ownership** for a bring-your-own number. A client
can connect a number they do not control; they cannot steal one already claimed, but
they could pre-claim an unclaimed DID. Real verification needs an OTP call or SMS to
the number.

### H13 — Calls left stuck as `active` with 0s duration
**Status: DONE — verified 6/7 (the one failure was the test's own assumption)**
`jobs/call_sweeper.py`, `services/repository.py`, `models`, `db.py`, `app.py`, `settings.py`

Seen on the real verification call: LiveKit's native layer panics during Windows
call teardown and kills the worker before the agent's best-effort "call ended"
report goes out, leaving the row `active` with `duration: 0` permanently. The
dashboard then shows calls that never end and average duration is dragged to zero.

Added `call_logs.last_activity_at` (bumped on every transcript turn) and a sweeper
that runs every 5 minutes, closing `active` rows older than
`CALL_STALE_AFTER_MIN` (15). Duration comes from the **last transcript turn**, not
from "now", so a row swept late does not invent a long call. A row with no turns at
all is marked `failed` — nothing was ever said.

Verified: a stale call with a transcript → `completed` with a 72s duration (matching
its real length, not the 40 minutes since it started) · a stale call with no
transcript → `failed`, 0s · a call one minute old is **not** touched · a second pass
is a no-op. The single "failure" was my assertion that exactly 2 rows would close —
3 did, because it also cleaned up the owner's real stuck call, which was the point.

### H2 — Audit trail
**Status: DONE — verified 13/13**
`models.AuditLog`, `services/audit.py`, wired into `routes/auth.py`,
`routes/phone_numbers.py`, `routes/admin.py`, `routes/clinics.py`

Nothing recorded who did what. A suspended account, a plan change, a claimed number
and a password reset all left no trace beyond an application log line that rotates
away, so an incident could not be reconstructed.

New append-only `audit_logs` table. Recorded: logins (success and failure, with the
reason), account lockouts, registration, password change/reset, "log out
everywhere", number connect/provision/remove (including provisioning **refused** at
the plan cap, which is a useful upgrade signal), superadmin plan changes with
before/after values, and settings updates.

Design points worth keeping:
* **Never breaks the caller.** Every write is best-effort and swallows its own
  errors — auditing must not fail the action being audited.
* **Its own session**, so an audit row is not rolled back with the caller's
  transaction. Failed actions are often the interesting ones.
* **No secrets.** Settings updates record field **names** only, never values —
  that payload carries the WhatsApp access token and the AI system prompt. A
  key-name filter redacts anything resembling a credential as a backstop.
* Actor email is denormalised so the trail survives the user being deleted.

Reads: `GET /api/clinics/activity` (tenant-scoped timeline) and
`GET /api/admin/audit-logs` (platform-wide, superadmin only, paginated).

Verified live: all five event types recorded · failures marked `outcome=failure` ·
**no password or access token anywhere in the trail** · client IP captured ·
clinic B cannot see clinic A's entries · the activity endpoint requires auth and the
platform log is superadmin-only (403 for a normal user).

### H3 — Unsafe with more than one replica
**Status: DONE — verified with two real backend processes**
`services/events.py`, `services/job_lock.py`, `jobs/reminder_worker.py`,
`jobs/call_sweeper.py`, `app.py`, `db.py`

Two distinct defects, both invisible with a single process:

1. **Notifications.** Fan-out was in-process only. A dashboard holds its WebSocket
   to one replica; if the agent's "call started" request lands on another, the
   publish happens where nobody is listening and the bell never fires. Adding a
   replica made notifications look like a flaky UI. `publish()` now also goes
   through Redis pub/sub and each process re-delivers to its own subscribers,
   ignoring its own echo. Falls back to in-process with a warning when Redis is
   absent.
2. **Duplicate WhatsApp reminders.** Both replicas read the same appointment with
   `reminder_sent = False` and both send — the flag is written only after sending.
   That is a customer-visible defect, not a performance issue.

**A correction worth recording: my first implementation used a Postgres advisory
lock, and that was wrong for this database.** Measured against the live instance:
this connection goes through Supabase's pooler (`app=Supavisor`), three separate
sessions from one process all landed on the **same** backend pid, and locks taken by
a process that had already exited were still held on an idle pooled backend. So two
"replicas" could share a backend and both think they own the job, and a crashed
owner would wedge it permanently — exactly the failure advisory locks were supposed
to prevent. One stranded lock from that experiment remains on a pooled backend; it
is inert (no code takes advisory locks any more) and clears when Supavisor recycles
that backend.

Replaced with a **lease row** (`job_leases`): ordinary data written in a
transaction, so pooling is irrelevant, and it expires on its own if the owner dies.
Acquire and renew are one atomic `INSERT … ON CONFLICT … WHERE expired OR mine`, so
there is no check-then-take race. Renewal runs on a **separate heartbeat** (TTL/3)
rather than after each pass — otherwise the 90s TTL would have to exceed the 300s
work interval, and a crashed owner would stall the job for at least five minutes.
A process that loses its lease stops working immediately instead of racing the new
owner.

Verified: lease acquired · a second replica refused while it is live · owner renews
repeatedly · an expired lease is taken over · release hands over at once · separate
jobs are independent · the lease survives pooled backend reuse. Then end-to-end with
two real uvicorn processes: replica 1 acquired both jobs, replica 2 logged
"owned by another process; standing by", and after killing replica 1, replica 2
took both jobs over ~60s later.

### Still open

| ID | Issue | File | Effort |
|---|---|---|---|
| H1 | JWT in `localStorage` → any XSS is account takeover. Needs HttpOnly+Secure+SameSite cookie + CSRF token. Touches the teammate's panel, so it needs coordination. | `frontend/src/lib/api.js`, `store/authStore.js` | 1d |
| H9b | No proof of **ownership** for a bring-your-own number. A client cannot steal a number another tenant already holds, but can pre-claim an unclaimed DID. Needs an OTP call or SMS. | `routes/phone_numbers.py` | 4h |
| H11 | Plan prices are `null`, so checkout is unreachable — we cannot charge anyone. Needs a pricing decision, not just code. | `services/plans.py` | 2h + decision |
| H12 | Agent runs on a Windows laptop; the webhook is an ngrok URL; 2-client concurrency has never been tested. Also removes the cause of H13. | infra | 1d |

**H2, H3, H4, H5, H6, H7, H8, H9, H10 and H13 are DONE** — each has its own section
in this file with what was wrong, what changed, and how it was verified.

### H5 — Email verification
**Status: DONE — verified 12/12**

Anyone could register any address, which mattered more than usual because platform
super-admin is granted by the **SUPERADMIN_EMAILS allowlist**: whoever registered an
allowlisted address FIRST became platform admin over every tenant, with no mailbox
check. Added `users.email_verified_at`, a single-use 24h token, `POST
/auth/verify-email` and a session-gated `POST /auth/resend-verification` (so it
cannot spam a stranger's mailbox). Issuing a new link invalidates the previous one.

`require_superadmin` now requires a **verified** address — but only when SMTP is
configured, because with no mail delivery verification cannot be completed and
refusing would lock the owner out of their own admin panel. Missing SMTP is now a
production blocker, so it cannot stay unenforced. Login is deliberately **not**
blocked on verification; `email_verified` is returned from `/auth/me`, login and
register so the dashboard can prompt.

### H6 — Reproducible builds
**Status: DONE** (container hardening landed with C6)

All 34 dependencies pinned to the versions the app is verified against; `>=` meant
two builds of one commit could install different code. Removed as unused (zero
imports): **celery** and **apscheduler** (background work is asyncio tasks elected by
`job_lock`), **loguru** (stdlib `logging` is used), **openai** (went with the legacy
`/media-stream` pipeline), **razorpay** (`razorpay_client.py` uses httpx + `hmac`).

### H7 — Migrations with a rollback path
**Status: DONE — live database stamped, no drift**

Alembic added, with `env.py` reusing the app's connection logic so migrations inherit
the pooler settings and the pinned CA. **Two real problems surfaced while
baselining:** the first autogenerated migration wanted to **DROP** `job_leases` and
four indexes (they existed in the database via raw SQL but not in the model
metadata) — discarded, and they are now declared as a model and `__table_args__`; and
three `users` columns had a database default but only a Python-side one on the model.
After both, autogenerate produces an **empty** diff, proving models and database
agree. The live database is stamped `0001_baseline` (version row written, no DDL run)
and `alembic check` reports no pending operations. Boot-time schema sync is behind
`DB_AUTO_SCHEMA`, flagged as a production blocker; CI proves every migration is
reversible with upgrade → downgrade → upgrade on a throwaway Postgres.

### H10 — CI and the tests that actually matter
**Status: DONE — 11 tests → 90, all passing**

`test_security_contracts.py` (66 tests, no database) has one case per hole found in
this audit, so a refactor cannot silently undo a fix. `test_tenant_isolation.py`
(13 tests, needs a database) registers two real clinics and proves B cannot read,
edit or delete A's contacts, see its settings, call logs or activity, claim a number A
holds (including digit variants), or reach platform admin — and that revoking a
session really stops the token. It skips itself without a database so CI stays green
without production credentials.

CI runs four jobs: backend (import, lint, tests, plus a guard that fails if the
security suite ever collects fewer than 50 tests — a suite that quietly vanishes is
worse than none, because the badge stays green), a secret scan that also asserts
`.env` is untracked and `.dockerignore` covers `.env` and `.git`, frontend lint and
build, and migration reversibility.


## MEDIUM

### M1 — Billing month was anchored to UTC, not the billing timezone
**Status: DONE — demonstrated**
new `services/billing_period.py`, used by `routes/billing.py`, `routes/admin.py`,
`services/repository.py`

Three separate copies computed the month as midnight **UTC** on the 1st. The business
runs in India (UTC+5:30) and `created_at` is naive UTC, so for the first 5h30m of
every month, calls made that morning IST were billed to the month that had already
closed — and counted against a quota already spent, which could refuse a call the
customer was entitled to. Demonstrated: a call at 02:00 IST on 1 Aug is stored as
`2026-07-31 20:30 UTC`; under the old boundary it was **not** in August, under the new
one it is. One helper now, so the three copies cannot drift.
`BILLING_UTC_OFFSET_MINUTES` covers a business elsewhere.

### M3 — Call history could not be paged
**Status: DONE**
`routes/calls.py`, `utils/helpers.py`

A hard `LIMIT 100` with no offset, so a busy clinic could not reach older calls — an
eleventh page did not exist. Now paginated with a total, plus status and phone/name
filters, served by the `(clinic_id, created_at DESC)` index. `api_response` gained an
optional `meta` block, so `data` keeps its existing shape and current dashboard code
is unaffected.

### M11 — Double bookings and duplicate token numbers under concurrency
**Status: DONE — proven with a 10-way concurrency test**
`services/repository.py`, `routes/calls.py`, `routes/appointments.py`

Two read-then-write races, both customer-visible:
* **time mode** — `is_slot_available` ran in its own session, then the insert happened
  separately, so two callers asking for the same slot both passed the check;
* **token mode** — `SELECT max(token_number)` then insert `max + 1`, so two callers
  read the same maximum and were both handed the **same token number**.

Fixed with `pg_advisory_xact_lock` per clinic, taken at the start of the booking
transaction, plus an overlap check that runs **in that same transaction**. Transaction
-scoped is the key detail: it releases at COMMIT, which is safe behind the pooler,
unlike the session-scoped lock that leaked in H3. Applied to **both** writers — the
agent and the dashboard — since locking only one would leave a race between a staff
member and the AI booking at the same instant.

Measured, 10 simultaneous bookings: **before** — tokens `[1,1,1,1,1,2,2,2,2,2]` and
5 appointments stored in one slot. **After** — tokens `[1..10]`, and exactly 1
booking won the slot with 9 told it was taken.

*(That test also caught a process mistake worth remembering: the first two runs still
showed the bug because the new backend had silently failed to bind — port 8000 was
still held — so the test was talking to the old code. Always confirm the restart
actually took.)*

### M12 — A pending payment could be forced into "failed"
**Status: DONE**
`routes/billing.py`

`/billing/verify` marked the payment `failed` whenever the signature did not match.
But a bad signature only proves **that request** was not signed by Razorpay; it says
nothing about the real payment, which may still be in flight. Anyone in the tenant who
knew an order id could push a pending order into a terminal state, and the genuine
webhook would then find it already closed. Now it rejects the request, logs, and
audits — without touching payment status. The signed webhook remains the only
authority on outcome.

## MEDIUM — still open

`M2` `tenants.whatsapp_access_token` stored plaintext — encrypt at rest with an app
key (3h) · `M4` naive `datetime.utcnow()` throughout and `DateTime` columns without
`timezone=True`; M1 fixed the billing arithmetic at the boundary, but the storage
convention is still naive UTC and converting it is a large, regression-prone
migration (4h+, do it deliberately) · `M6` no soft deletes, retention policy or GDPR
delete (1d) · `M10` no Sentry / OpenTelemetry / log aggregation (1d).

**Done:** `M1` billing month boundary · `M3` call-log pagination ·
`M5` composite tenant indexes (with H13) · `M7` dead code removed — the websocket
handler and `integrations/minimax/{llm,stt,tts}.py` went with C1, and `require_roles`
is now covered by the C4 plan · `M8` `password_hash` stripped from the request-scoped
user (with C3) · `M9` Pydantic v1 `.dict()` replaced with `model_dump` in the routes
that were touched · `M11` booking concurrency · `M12` payment force-fail.

## LOW — still open

`clinic_id` naming in a multi-industry product · no dark mode / notification centre / knowledge base · a11y: focus trap in `Modal`, ARIA on `DataTable` · Dashboard chunk 110 KB gzip (recharts) — lazy-load charts below the fold · `/` leaks the version · no `security.txt`.

---

## Missing before launch (product, not bugs)

**Must:** staff/team management + invites · permission matrix UI · audit log +
activity timeline · company suspend/activate/delete · email verification · plan
prices + working checkout · invoices · data export · account deletion.
**Should:** MFA · session/device list · login history · notification centre · API
keys + customer webhooks · usage alerts at 80/100%.
**Later:** impersonation (with a mandatory audit entry) · CRM integrations ·
recording management · feature flags · dark mode.

---

## Launch gate

Not ready to sell yet, but the cross-tenant and session holes are closed.

All four CRITICAL code issues are closed (C1, C2, C3, C6), and so are ten of the
twelve HIGH items plus five MEDIUM ones. Nothing exploitable is knowingly left.

**Remaining before a client touches this:**

| ID | What | Who |
|---|---|---|
| C4 | RBAC hierarchy (Super Admin → Company Admin → Staff) | waiting on the teammate's Staff Panel push |
| C5 | Rotate `JWT_SECRET` — currently 19 characters | owner, doing last |
| H12 | Agent on Linux + a stable HTTPS domain instead of ngrok; test 2 clients concurrently | infra |
| H11 | Set plan prices so checkout works | pricing decision |
| H1 | Move the session token out of `localStorage` into an HttpOnly cookie | needs coordination with the teammate |
| H9b | Prove ownership of a bring-your-own number (OTP) | 4h |

Plus operator actions: add `REDIS_PASSWORD` to `.env` (compose will not start
without it), configure SMTP, set `DB_AUTO_SCHEMA=false`, and build the image once
(`docker build` has still never been run — the daemon was off).

Realistic: **~1 focused week** to launch-ready, most of it H12 and C4. A two-client
pilot is reachable in ~2 days once C5, Redis and SMTP are set and the agent is on
Linux.

### Verification snapshot (end of this pass)

| Check | Result |
|---|---|
| `pytest backend/tests` | **90 passed** (was 11) |
| `alembic current` | `0001_baseline (head)` |
| `alembic check` | No new upgrade operations detected |
| `/health` local + tunnel | 200, `database: ok` |
| Dashboard | 200 |
| Agent worker | one only, registered `clarivo-inbound`, India South |
| Frontend build / lint | 0 errors / 0 problems |
| Secret scan of the tracked tree | clean |
| Temporary `_*.py` scripts | none left |
| Synthetic test data | all probe users, clinics and call rows deleted, deletion confirmed |

### Verification snapshot (2026-08-05)

| Check | Result |
|---|---|
| `python -c "import backend.app"` | OK |
| `pytest backend/tests` | 11/11 pass |
| C2 agent-scoping suite | 11/11 pass |
| C3 session-revocation suite | 10/10 pass |
| C1 removal suite | 5/5 pass |
| `GET /health` (local + tunnel) | 200, `database: ok` |
| Dashboard | 200 |
| Agent worker | registered as `clarivo-inbound`, India South |
| Security headers | 7 present |
| C6 compose config | valid; redis unpublished; no bind mount; requirepass set |
| **Real inbound call through the new token flow** | **PASS** — `call_918081353242_BLAzwkfoF9zw` resolved to the right clinic and saved 6 transcript turns, which means the scoped-token + matching-`call_id` check passed on every turn. LLM ttft 1.4-1.5s, TTS ttfb 0.58s, `end_call` fired. |

**Not verified:** `docker build`. The Docker daemon was off on the dev machine, so
the new multi-stage image was never actually built — only the compose config was
checked (that is client-side). Build it once before relying on it.

Caveat from that same call: it is stored as `status: active, duration: 0s` because
the Windows teardown panic killed the worker before `agent-call-end` fired. That is
**H13**, not a token problem.

### Temporary scripts

All `_*.py` probes used for the above were deleted after use, and every synthetic
row they created (`call_AAA`, `_c1probe_*`, the throwaway user + its tenant) was
removed and the removal confirmed. No test data is left in the client database.
