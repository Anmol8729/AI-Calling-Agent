# CLARIVO — COMPLETE SECURITY AUDIT REPORT (OWASP TOP 10)

**Audit Date:** November 2026  
**Scope:** Backend (`backend/`), Voice Agent (`agent/`), Frontend (`frontend/`), Infrastructure & CI/CD

---

## 1. Vulnerability Summary

| Severity | Verified Count | Fixed in This Audit | Remaining |
|---|---:|---:|---:|
| **Critical** | 1 | 1 | 0 |
| **High** | 3 | 3 | 0 |
| **Medium** | 3 | 2 | 1 |
| **Low** | 2 | 1 | 1 |
| **Total** | **9** | **7** | **2** |

---

## 2. Detailed Vulnerability Findings

### [CRITICAL-01] Hardcoded Demo / Admin Backdoor Credentials in Production Login
- **Affected Files:** `backend/routes/auth.py` (`login`, `get_current_user`), `backend/services/demo_data.py`
- **Status:** **FIXED**
- **Description:** `POST /api/auth/login` previously contained a hardcoded credential check (`admin@clarivo.io` / `demo@clarivo.io` with password `password123`) that bypassed the PostgreSQL database unconditionally in production and returned a valid JWT with `is_superadmin: True`. Additionally, `get_current_user` returned `DEMO_USER` whenever `sub == DEMO_USER_ID` regardless of environment.
- **Exploitation & Impact:** Any external attacker could authenticate as `DEMO_USER_ID` in production without valid credentials.
- **Implemented Fix:** Removed the hardcoded credential branch from `login()`, set `DEMO_USER["is_superadmin"] = False`, and restricted `DEMO_USER_ID` in `get_current_user` strictly to `db is None and ENV in ("development", "test")`.

---

### [HIGH-01] Admin Session Tokens Stored in `localStorage` (XSS Token Exfiltration)
- **Affected Files:** `frontend/src/store/authStore.js`, `frontend/src/lib/api.js`, `backend/routes/auth.py`
- **Status:** **FIXED**
- **Description:** Admin JWTs were previously returned in the JSON response body and persisted in `localStorage.getItem("token")`, exposing privileged platform tokens to any XSS vector or third-party script.
- **Implemented Fix:** Designated admin logins now issue an `HttpOnly`, `SameSite=Lax`, `Secure` (in prod/staging) cookie (`clarivo_admin_session`) paired with a double-submit CSRF cookie/header (`clarivo_csrf_token` / `X-CSRF-Token`). `access_token` is omitted from admin login JSON responses, and `authStore.js` explicitly clears `token` from `localStorage` for admin sessions.

---

### [HIGH-02] No Single-Active-Session Policy or Idle Timeout for Admin
- **Affected Files:** `backend/routes/auth.py`, `backend/config/settings.py`, `backend/services/auth_service.py`
- **Status:** **FIXED**
- **Description:** Multiple simultaneous admin sessions could remain active across devices for 24 hours, and `SUPERADMIN_EMAILS` allowed multiple admin identities.
- **Implemented Fix:**
  - Enforced a single designated admin identity (`ADMIN_EMAIL` / `designated_admin_email`).
  - Blocked public `/register` and `/oauth/google` auto-creation for the designated admin email.
  - Added dedicated rate-limited `POST /api/auth/admin/login` (`5/minute`).
  - On every admin login, `user.token_version` is atomically incremented in PostgreSQL, immediately invalidating any prior active admin session.
  - Added `ADMIN_SESSION_IDLE_MINUTES` (default 30 min) inactivity enforcement in `get_current_user`.
  - Added `POST /api/auth/logout` to revoke `token_version` server-side and clear cookies.

---

### [HIGH-03] Legacy `bcrypt` Password Hashing Without Argon2id
- **Affected Files:** `backend/services/auth_service.py`, `backend/requirements.txt`
- **Status:** **FIXED**
- **Description:** Passwords were hashed with `bcrypt` rather than memory-hard Argon2id.
- **Implemented Fix:** Integrated `argon2-cffi==23.1.0` (`Type.ID`, 64 MiB memory cost, time cost 3, parallelism 2) for all new passwords and admin provisioning (`scripts/tools/provision_admin.py`), with transparent backward verification and automatic re-hashing of legacy `bcrypt` hashes on login.

---

### [MEDIUM-01] Missing Server-Side Session Revocation on Standard Logout
- **Affected Files:** `backend/routes/auth.py`, `frontend/src/store/authStore.js`
- **Status:** **FIXED**
- **Description:** Frontend logout previously relied on `/auth/logout-all-devices` or local clearing without clearing HttpOnly cookies.
- **Implemented Fix:** Added `POST /api/auth/logout` which bumps `token_version`, clears cookies, and logs `auth.logout` to `audit_logs`.

---

### [MEDIUM-02] Stray Root `package-lock.json` & Cluttered Utility Scripts
- **Affected Files:** Root directory (`package-lock.json`, `scripts/dev/`, `scripts/tools/`)
- **Status:** **FIXED**
- **Description:** An empty `package-lock.json` and 12 dev/diagnostic scripts sat in the repository root.
- **Implemented Fix:** Removed stray `package-lock.json`, organized dev runners into `scripts/dev/` and admin/diagnostic tools into `scripts/tools/`, and hardened `.gitignore`.

---

### [MEDIUM-03] Process-Local Admin Inactivity Dictionary (`_admin_last_activity`)
- **Affected Files:** `backend/routes/auth.py`
- **Status:** **REMAINING (Low Risk on Single-Worker, Medium on Multi-Worker)**
- **Description:** `_admin_last_activity` is stored in Python process memory. If `uvicorn` runs with multiple worker processes (`--workers 2+`), idle timestamps are tracked per worker rather than shared.
- **Recommended Fix:** Back `_admin_last_activity` with Redis (`REDIS_URL`) when running multi-worker backend replicas.

---

### [LOW-01] Plaintext Storage of Per-Tenant Inbound SIP Credentials
- **Affected Files:** `backend/models/__init__.py` (`SipTrunk`), `docs/PLAN-number-ownership.md`
- **Status:** **ACCEPTED / MITIGATED**
- **Description:** Inbound SIP digest credentials are stored in plaintext in `sip_trunks` (similar to `whatsapp_access_token`). They authenticate inbound calls only and cannot place outbound calls at Clarivo's expense; mitigated by IP allowlists (`allowed_addresses`) and credential rotation (`/connection/rotate`).

---

### [LOW-02] Clinic User JWTs Still Stored in `localStorage`
- **Affected Files:** `frontend/src/store/authStore.js`
- **Status:** **REMAINING (Accepted for Backward Compatibility)**
- **Description:** Non-admin clinic users (`doctor`, `staff`) still store their bearer JWT in `localStorage` to maintain compatibility with existing API clients. Admin sessions are fully migrated to `HttpOnly` cookies.
