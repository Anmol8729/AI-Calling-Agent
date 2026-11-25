# CLARIVO — PRIORITIZED IMPROVEMENT ROADMAP

## Immediate (Pre-Launch / Completed)
- [x] **Remove Hardcoded Admin/Demo Backdoor** in `backend/routes/auth.py` *(Completed)*
- [x] **Single Designated Admin + Single Active Session + HttpOnly Cookie + CSRF** *(Completed)*
- [x] **Argon2id Password Hashing Upgrade** with transparent bcrypt migration *(Completed)*
- [x] **4-Minute Hard Call Duration Cap** (`AGENT_MAX_CALL_DURATION_SEC=240`) to bound variable AI cost *(Completed)*
- [x] **Repository Hygiene & Industry Standards** (`Makefile`, `SECURITY.md`, `CONTRIBUTING.md`, `LICENSE`) *(Completed)*

---

## Short-Term (Next 2–4 Weeks)

| Priority | Item | Complexity | Details |
|---|---|---|---|
| **P1** | **Redis-Backed Admin Idle Tracker** | Low | Move `_admin_last_activity` in `backend/routes/auth.py` to Redis so multi-worker `uvicorn` deployments share admin idle state. |
| **P1** | **Per-Call Usage & Cost Telemetry Table** | Medium | Persist `CallUsage` (LiveKit mins, Deepgram mins, LLM tokens, MiniMax TTS chars, computed INR cost) per `call_sid` idempotently. |
| **P2** | **Automated Integration CI Job** | Medium | Spin up an ephemeral PostgreSQL service container in `.github/workflows/ci.yml` so the 13 live HTTP tests in `test_tenant_isolation.py` run on every PR. |
| **P2** | **Clinic User HttpOnly Cookie Migration** | Medium | Optionally migrate clinic `doctor`/`staff` tokens from `localStorage` to `HttpOnly` refresh/access cookies as well. |

---

## Long-Term (Scale: 100 – 500 Clinics)

| Priority | Item | Complexity | Details |
|---|---|---|---|
| **P2** | **Horizontal Agent Worker Pool** | High | Scale LiveKit Python worker instances behind container orchestration once concurrent call volume exceeds 10–15 active calls. |
| **P3** | **Managed PostgreSQL HA & Read Replicas** | Medium | Upgrade from single-VPS local PostgreSQL to managed primary + read replica for analytics/stats queries above 50 clinics. |
| **P3** | **Real-Time Cost & Margin Admin Dashboard** | Medium | Surface per-clinic gross margin, provider spend alerts (80%/100% plan usage), and fallback frequency in `/admin`. |
