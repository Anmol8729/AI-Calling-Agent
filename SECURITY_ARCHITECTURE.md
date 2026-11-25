# CLARIVO — SECURITY ARCHITECTURE

**Target System:** Clarivo Multi-Tenant AI Calling Receptionist & Practice Management SaaS

---

## 1. End-to-End Trust Boundaries & Data Flow

```text
  [Browser / React 19 SPA]
     │  • Clinic User: Bearer JWT (localStorage)
     │  • Admin User:  HttpOnly Cookie (clarivo_admin_session) + X-CSRF-Token
     ▼  (HTTPS / TLS 1.3 via Caddy Reverse Proxy)
  [FastAPI Edge Middleware]
     │  1. MaxBodySizeMiddleware (2 MiB payload cap -> 413)
     │  2. SecurityHeadersMiddleware (HSTS, CSP, X-Frame-Options: DENY, nosniff)
     │  3. CORSMiddleware (Explicit origin allowlist, allow_credentials=True)
     │  4. SlowAPI Rate Limiter (Redis / Memory token bucket)
     ▼
  [Authentication & Session Gate (`backend/routes/auth.py`)]
     │  • Argon2id (Type.ID) password hashing + legacy bcrypt upgrade
     │  • RFC 6238 TOTP MFA (optional/enforced via ADMIN_TOTP_SECRET)
     │  • Single Designated Admin (`ADMIN_EMAIL`) + Atomic `token_version` rotation
     │  • Redis-backed Admin Idle Timeout (`ADMIN_SESSION_IDLE_MINUTES`)
     ▼
  [Authorization & Tenant Isolation]
     │  • `get_current_user` -> verifies `token_version`, `is_active`, `tenant.status`
     │  • `require_superadmin` -> designated admin + email verified
     │  • `require_non_staff` / `require_roles` -> RBAC enforcement
     │  • Every query filtered by `clinic_id` from verified JWT claims
     ▼
  [Database & External Trust Domains]
     ├─ PostgreSQL 16 (asyncpg + Pinned CA TLS `backend/certs/`)
     ├─ Redis 7 (Rate limits, Admin idle TTL, Pub/Sub event bridge)
     ├─ LiveKit Voice Worker (`agent/main.py`) -> Scoped per-call JWT (`_CALL_TOKEN`)
     └─ Razorpay (Server-side plan lookup + HMAC-SHA256 webhook verification)
```

---

## 2. Cryptographic & Key Management Controls

| Secret / Key | Purpose | Storage & Rotation |
|---|---|---|
| `JWT_SECRET` | Signs dashboard session JWTs (HS256) | Env only (≥32 chars enforced at boot) |
| `AGENT_INTERNAL_SECRET` | Signs single-call scoped agent JWTs | Separate env secret (`!= JWT_SECRET`) |
| `ADMIN_TOTP_SECRET` | Base32 key for admin RFC 6238 TOTP MFA | Env only; replay-protected per 30s window |
| `RAZORPAY_KEY_SECRET` / `WEBHOOK_SECRET` | Checkout & webhook HMAC verification | Env only; never sent to browser |
| `backend/certs/supabase-prod-ca-2021.crt` | Pinned PostgreSQL root CA | Public cert verified on DB TLS handshake |
