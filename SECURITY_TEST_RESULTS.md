# CLARIVO — SECURITY TEST RESULTS

**Test Execution Date:** November 2026  
**Environment:** Python 3.11.9 (`uv`) with `argon2-cffi`, Node.js 20+ / Vite 7.3.5

---

## 1. Automated Test Suite Summary

| Suite / Command | Passed | Failed | Skipped | Status |
|---|---:|---:|---:|---|
| `pytest backend/tests -v` | **166** | **0** | **13** | **PASS** |
| `python backend/tests/_assert_suite_size.py` | **135 contracts** | **0** | **0** | **PASS** |
| `npm --prefix frontend run build` | **2,472 modules** | **0** | **0** | **PASS** |

> **Note on Skipped Tests:** The 13 skipped tests in `backend/tests/test_tenant_isolation.py` are live HTTP end-to-end tests that automatically skip when no live backend + PostgreSQL server is listening at `http://127.0.0.1:8000`.

---

## 2. Security Controls Verified by Execution

### Authentication & Password Security
- **Argon2id Hashing & Bcrypt Backward Compatibility:** Verified `$argon2id$` generation, verification, wrong-password rejection, and `password_needs_rehash(legacy_bcrypt) == True`.
- **Hardcoded Backdoor Removal:** Verified `password123` and `admin@clarivo.io` are absent from `backend/routes/auth.py` and `DEMO_USER["is_superadmin"] is False`.
- **Timing-Safe Login & Account Lockout:** Verified `_DUMMY_PASSWORD_HASH` timing equalization and `login_guard` escalating lockout.
- **Password Strength & Reuse Across Paths:** Verified `validate_password_strength` applies across signup, change-password, reset-password, and staff creation.

### Admin Panel & Single-Active-Session Security
- **Single Designated Admin:** Verified `is_superadmin()` accepts only `ADMIN_EMAIL` (case-insensitive) and rejects other emails.
- **No Public Admin Registration:** Verified `register()` and `google_sign_in()` block creating the designated admin email (`403`).
- **Single Active Admin Session:** Verified `login()` atomically bumps `user.token_version`, rotates `jti`, sets `HttpOnly` + `CSRF` cookies, and omits `access_token` from JSON.
- **Admin TOTP MFA + Replay Protection:** Verified RFC 6238 `verify_totp()` accepts valid current 6-digit codes, rejects invalid codes, and rejects replaying the same code in the same 30-second window.
- **Admin Idle Timeout & Logout:** Verified `get_current_user` checks Redis (`clarivo:admin_idle:...`) + fallback memory timer, and `/api/auth/logout` bumps `token_version` and clears cookies.
- **Zero `localStorage` Admin Token Storage:** Verified `frontend/src/store/authStore.js` removes `token` from `localStorage` for admin sessions and `api.js` sends `withCredentials: true` + `X-CSRF-Token`.

### API, Middleware & Tenant Isolation Contracts
- **HSTS & Security Headers:** Verified `SecurityHeadersMiddleware(hsts=True)` emits `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and CSP headers.
- **Request Body Size Cap:** Verified `MaxBodySizeMiddleware(max_bytes=32)` rejects oversized payloads with `413 Content Too Large`.
- **Per-Call Agent Scoped Tokens & RBAC:** Verified all 135 contract assertions in `test_security_contracts.py` (`staff` write restrictions, `pg_advisory_xact_lock`, XML webhook escaping, Razorpay HMAC verification).
