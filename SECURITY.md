# Security Policy

## Supported Versions

| Version / Branch | Supported |
|---|---|
| `main` (Production) | ✅ Active |
| `security-hardening` | ✅ Active |

## Security Architecture

Clarivo enforces defense-in-depth across its multi-tenant clinical SaaS stack:

- **Strict Tenant Isolation:** Every database query, appointment slot, call log, and patient record is scoped to `clinic_id` extracted from verified JWT claims.
- **Per-Call Scoped Agent Tokens:** The LiveKit voice worker receives a short-lived, single-call JWT token scoped strictly to one `clinic_id` and `call_id` rather than using global admin credentials.
- **Authentication Hardening:** JWT session revocation (`token_version`), failed login lockout, password complexity rules, and SlowAPI rate limiting.
- **Database & Transport Security:** Pinned TLS CA certificate verification for PostgreSQL (`backend/certs/`), advisory transaction locks (`pg_advisory_xact_lock`) for double-booking prevention, and append-only `audit_logs`.
- **CI Secret Scanning:** Automated credential scanning and `.env` / `.dockerignore` verification on every push and pull request (see `.github/workflows/ci.yml`).
- **Telecom Compliance (Option A / BYON):** Clinics own and authenticate their own numbers via per-tenant LiveKit SIP inbound trunks with digest credentials.

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public GitHub issue.

1. Contact the engineering team privately with a detailed description, steps to reproduce, and potential impact.
2. Allow up to 48 hours for initial triage and acknowledgement.
3. Please refrain from public disclosure until a fix has been released and verified.
