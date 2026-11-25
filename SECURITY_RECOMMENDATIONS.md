# CLARIVO — SECURITY RECOMMENDATIONS & MANUAL HOSTING CONTROLS

---

## 1. Controls Requiring Manual Hosting / Infrastructure Configuration

These items cannot be enforced purely inside application source code and must be verified on the production host (`157.20.190.64`) and DNS/CDN:

1. **Provision Single Designated Admin & TOTP MFA:**
   - Set `ADMIN_EMAIL` in production `.env`.
   - Generate a Base32 TOTP secret and set `ADMIN_TOTP_SECRET` in `.env`, then scan/import it into an authenticator app.
   - Run `python scripts/tools/provision_admin.py` to create/rotate the admin account with Argon2id.
2. **Firewall & Network Isolation (`ufw` / Cloud Security Group):**
   - Expose **only** ports `80/tcp`, `443/tcp` (Caddy TLS), and your restricted SSH port (`8800/tcp`, ideally key-only auth with `PasswordAuthentication no`).
   - Bind PostgreSQL (`5432`) and Redis (`6379`) strictly to `127.0.0.1` / Unix sockets.
3. **Database Backups & Restore Verification:**
   - Configure automated daily encrypted `pg_dump` backups to off-host object storage and test restoration quarterly.
4. **WAF / DDoS Edge Protection:**
   - Enable Cloudflare WAF / rate-limiting rules in front of `app.clarivo.net.in` and `api.clarivo.net.in`.
5. **Indian DPDP Compliance (Patient PII):**
   - Publish a Privacy Policy covering patient phone numbers, names, and call transcripts.
   - Implement a self-serve or admin-triggered tenant data export & deletion workflow for DPDP "Right to Erasure" requests.

---

## 2. Optional Future Hardening

1. **Migrate Clinic User (`doctor` / `staff`) Tokens to HttpOnly Cookies:**
   - Admin sessions now use `HttpOnly` + `SameSite=Lax` + CSRF cookies. Migrating standard clinic user sessions to `HttpOnly` cookies with refresh-token rotation will eliminate `localStorage` JWT usage across all user tiers.
2. **Execute Live HTTP Integration Suite in CI:**
   - Add a CI job that boots FastAPI against the scratch Postgres container so all 13 tests in `backend/tests/test_tenant_isolation.py` run automatically on every push.
3. **Secret Rotation After Historical Cleanup:**
   - Because `admin@clarivo.io` / `password123` previously existed in Git history, ensure production `.env` uses fresh, high-entropy secrets (`JWT_SECRET`, `AGENT_INTERNAL_SECRET`, `ADMIN_TOTP_SECRET`) and no legacy test accounts exist in the production `users` table.
