import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App Settings
    ENV: str = os.getenv("ENV", "development")
    SERVER_URL: str = os.getenv("SERVER_URL", "http://localhost:8000")
    # Comma-separated list of browser origins allowed by CORS (the dashboard).
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173")
    # Public URL of the dashboard, used to build password-reset / invite links.
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:3000")

    # Shared secret the LiveKit voice agent uses to call the internal booking
    # endpoint (POST /api/calls/agent-book). Set the SAME value in .env so both
    # the backend and the agent read it. Empty => the endpoint is disabled (401),
    # so the agent cannot write bookings until this is set.
    AGENT_INTERNAL_SECRET: str = os.getenv("AGENT_INTERNAL_SECRET", "")
    # Lifetime of the per-call token the agent receives from /agent-context. It
    # scopes the agent to ONE clinic + ONE call, so the shared secret above is no
    # longer a master key over every tenant. Must outlast a real conversation.
    AGENT_CALL_TOKEN_TTL_MIN: int = int(os.getenv("AGENT_CALL_TOKEN_TTL_MIN", "45") or "45")
    
    # Database Settings (Supabase Postgres)
    # Two ways to configure it (DATABASE_URL wins if it is set):
    #   1. DATABASE_URL = full postgresql:// URI (driver is normalised in db.py).
    #   2. The DB_* parts below. Preferred when the password contains special
    #      characters (@, #, :, /) because NO URL-encoding is needed here.
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_HOST: str = os.getenv("DB_HOST", "")
    DB_PORT: int = int(os.getenv("DB_PORT", "6543") or "6543")
    DB_NAME: str = os.getenv("DB_NAME", "postgres")
    
    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Auth Settings
    JWT_SECRET: str = os.getenv("JWT_SECRET", "super-secret-receptionist-key-change-this-in-production")
    JWT_ALGORITHM: str = "HS256"
    # Session length. Was a hardcoded 7 days, which is a long window for a stolen
    # token; 24h is the usual choice for a business dashboard. Sessions can now be
    # revoked before expiry (users.token_version), so this is a ceiling, not the
    # only control. Raise it via .env if daily sign-in is too much friction —
    # proper refresh-token rotation is the follow-up that removes the tradeoff.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24)) or str(60 * 24)
    )

    # Platform super-admins (comma-separated emails). Users whose login email is
    # listed here can access /admin (assign plans / custom allowances across all
    # tenants). Everyone else is 403. Set this in .env to your own email(s).
    SUPERADMIN_EMAILS: str = os.getenv("SUPERADMIN_EMAILS", "")

    # Monthly call-quota enforcement on inbound calls. OFF by default and
    # fail-open (any error while checking -> the call is allowed). When ON, calls
    # beyond a tenant's monthly allowance are answered with QUOTA_EXCEEDED_MESSAGE
    # and ended.
    ENFORCE_CALL_QUOTA: bool = os.getenv("ENFORCE_CALL_QUOTA", "false").lower() == "true"

    # Read by the voice agent, declared here only so check_production_config() can
    # refuse to boot when it is set. It MUST be a declared field: pydantic-settings
    # loads `.env` into this model, not into os.environ, so `os.getenv` in the guard
    # returned None and the check silently never fired.
    AGENT_LLM_PROVIDER: str = os.getenv("AGENT_LLM_PROVIDER", "")
    QUOTA_EXCEEDED_MESSAGE: str = os.getenv("QUOTA_EXCEEDED_MESSAGE", "Sorry, we are unable to take your call at the moment. Please try again later.")

    # Payments (Razorpay). Self-serve plan upgrades are enabled only when both
    # KEY_ID and KEY_SECRET are set; otherwise the dashboard shows "Request
    # upgrade" instead of a pay button. KEY_ID is public (used by checkout.js);
    # KEY_SECRET and WEBHOOK_SECRET must never reach the browser.
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    @property
    def payments_enabled(self) -> bool:
        return bool(self.RAZORPAY_KEY_ID and self.RAZORPAY_KEY_SECRET)

    # WhatsApp (Meta Cloud API) for appointment confirmations + reminders.
    # Enabled only when both the access token and phone number id are set.
    # Templates must be pre-approved in Meta Business Manager; each expects 3
    # body params in order: {{1}}=customer name, {{2}}=business, {{3}}=when.
    WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_API_VERSION: str = os.getenv("WHATSAPP_API_VERSION", "v22.0")
    # Prepended to 10-digit local numbers when normalising recipients (India=91).
    WHATSAPP_DEFAULT_COUNTRY_CODE: str = os.getenv("WHATSAPP_DEFAULT_COUNTRY_CODE", "91")
    # Must match the language of your approved templates (e.g. "en_US" or "hi").
    WHATSAPP_TEMPLATE_LANG: str = os.getenv("WHATSAPP_TEMPLATE_LANG", "en_US")
    WHATSAPP_CONFIRM_TEMPLATE: str = os.getenv("WHATSAPP_CONFIRM_TEMPLATE", "appointment_confirmation")
    WHATSAPP_REMINDER_TEMPLATE: str = os.getenv("WHATSAPP_REMINDER_TEMPLATE", "appointment_reminder")
    # Send the reminder once the appointment is within this many minutes.
    WHATSAPP_REMINDER_LEAD_MIN: int = int(os.getenv("WHATSAPP_REMINDER_LEAD_MIN", "120") or "120")
    # How often the reminder worker checks for due reminders (seconds).
    WHATSAPP_REMINDER_INTERVAL_SEC: int = int(os.getenv("WHATSAPP_REMINDER_INTERVAL_SEC", "300") or "300")

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.WHATSAPP_ACCESS_TOKEN and self.WHATSAPP_PHONE_NUMBER_ID)

    # Email (SMTP) for password reset + team invites. If SMTP_HOST is empty,
    # links are logged server-side instead of emailed (dev mode).
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587") or "587")
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "")
    SMTP_TLS: bool = os.getenv("SMTP_TLS", "true").lower() == "true"
    
    # MiniMax Configuration (LLM + TTS). Base URL is configurable per account/
    # region: international = https://api.minimax.io/v1 (default); mainland-China
    # accounts use a different host. The LLM endpoint is OpenAI-compatible.
    MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")
    MINIMAX_GROUP_ID: str = os.getenv("MINIMAX_GROUP_ID", "")
    MINIMAX_API_BASE: str = os.getenv("MINIMAX_API_BASE", "https://api.minimax.io/v1")
    MINIMAX_LLM_MODEL: str = os.getenv("MINIMAX_LLM_MODEL", "MiniMax-M3")
    MINIMAX_TTS_MODEL: str = os.getenv("MINIMAX_TTS_MODEL", "speech-02-turbo")
    MINIMAX_TTS_VOICE: str = os.getenv("MINIMAX_TTS_VOICE", "male-qn-qingse")
    # MiniMax TTS language hint for correct pronunciation (e.g. "Hindi", "English", "auto").
    MINIMAX_LANGUAGE_BOOST: str = os.getenv("MINIMAX_LANGUAGE_BOOST", "Hindi")

    # Speech-to-Text (ASR) via Deepgram. MiniMax does NOT offer STT.
    # Get a key at https://console.deepgram.com/. STT stays in mock mode while
    # DEEPGRAM_API_KEY is empty. nova-3 is Deepgram's current general model and
    # handles 8kHz phone audio well.
    DEEPGRAM_API_KEY: str = os.getenv("DEEPGRAM_API_KEY", "")
    DEEPGRAM_URL: str = os.getenv("DEEPGRAM_URL", "https://api.deepgram.com/v1/listen")
    # nova-2 supports Hindi (and 36+ languages); callers here speak Hindi.
    DEEPGRAM_MODEL: str = os.getenv("DEEPGRAM_MODEL", "nova-2")
    DEEPGRAM_LANGUAGE: str = os.getenv("DEEPGRAM_LANGUAGE", "hi")
    
    # Vobiz (Indian Calling) Configuration
    VOBIZ_SIP_DOMAIN: str = os.getenv("VOBIZ_SIP_DOMAIN", "")
    VOBIZ_USERNAME: str = os.getenv("VOBIZ_USERNAME", "")
    VOBIZ_PASSWORD: str = os.getenv("VOBIZ_PASSWORD", "")
    VOBIZ_OUTBOUND_NUMBER: str = os.getenv("VOBIZ_OUTBOUND_NUMBER", "")

    # Vobiz REST API (number provisioning). SEPARATE from the SIP username/
    # password above: these are the dashboard's "Auth ID" / "Auth Token" and use
    # HTTP Basic auth. Needed for one-click number provisioning, where a client
    # claims a number from the account's inventory and it is auto-routed.
    VOBIZ_AUTH_ID: str = os.getenv("VOBIZ_AUTH_ID", "")
    VOBIZ_AUTH_TOKEN: str = os.getenv("VOBIZ_AUTH_TOKEN", "")
    # Inbound trunk whose destination is our LiveKit SIP URI. Vobiz does NOT
    # auto-route new numbers — each DID must be assigned to this trunk. ONE trunk
    # serves every number, so this is a single one-time value.
    VOBIZ_TRUNK_GROUP_ID: str = os.getenv("VOBIZ_TRUNK_GROUP_ID", "")

    @property
    def number_provisioning_enabled(self) -> bool:
        """True when the dashboard can claim + route numbers by itself."""
        return bool(self.VOBIZ_AUTH_ID and self.VOBIZ_AUTH_TOKEN and self.VOBIZ_TRUNK_GROUP_ID)

    # ----- stale call cleanup ------------------------------------------------
    # A call still marked "active" this long after it started is assumed dead: the
    # agent's end-of-call report never arrived (it is best-effort, and the LiveKit
    # teardown panic on Windows can kill the worker first). Must exceed the longest
    # plausible real call, or a live conversation would be closed under it.
    CALL_STALE_AFTER_MIN: int = int(os.getenv("CALL_STALE_AFTER_MIN", "15") or "15")
    CALL_SWEEP_INTERVAL_SEC: int = int(os.getenv("CALL_SWEEP_INTERVAL_SEC", "300") or "300")

    # ----- Supabase Auth (Google sign-in ONLY) -------------------------------
    # Supabase Auth is used purely as a Google identity provider. It does NOT
    # replace this application's authentication: password sign-up, login, email
    # verification, password reset, session revocation, per-account lockout,
    # suspension and the audit trail all remain in `public.users` and
    # routes/auth.py, and every one of them is covered by tests. Adding a second
    # implementation of those would duplicate logic and lose those controls.
    #
    # Flow: the browser completes Google sign-in with Supabase, sends the
    # resulting Supabase access token to POST /api/auth/oauth/google, and the
    # backend exchanges it for this application's own session token. Everything
    # downstream (clinic scoping, roles, revocation) is unchanged.
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    # The ANON (public) key. Safe to expose to a browser — it only permits what
    # RLS allows. The SERVICE ROLE key must NEVER be added here or to any
    # frontend variable: it bypasses RLS entirely.
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

    @property
    def supabase_url(self) -> str:
        """Project URL, derived from the database user when not set explicitly.

        Supabase pooler usernames are `postgres.<project-ref>`, so the project URL
        can be inferred. One less value to keep in sync, and it cannot drift from
        the database the app is actually pointed at.
        """
        if self.SUPABASE_URL.strip():
            return self.SUPABASE_URL.strip().rstrip("/")
        user = (self.DB_USER or "")
        if "." in user:
            return f"https://{user.split('.', 1)[1]}.supabase.co"
        return ""

    @property
    def google_oauth_enabled(self) -> bool:
        """True when the backend can verify Supabase tokens.

        Without the anon key the OAuth endpoint returns 503 rather than trusting
        an unverified token.
        """
        return bool(self.supabase_url and self.SUPABASE_ANON_KEY.strip())

    # ----- billing period ----------------------------------------------------
    # Offset of the BILLING timezone from UTC, in minutes. 330 = IST (UTC+5:30).
    # Month boundaries used to be computed at midnight UTC, so for the first 5h30m
    # of each month calls made that morning in India were billed to the month that
    # had already closed — and counted against a quota already spent. A fixed offset
    # (not a named zone) is exact for India, which has no daylight saving.
    BILLING_UTC_OFFSET_MINUTES: int = int(
        os.getenv("BILLING_UTC_OFFSET_MINUTES", "330") or "330"
    )

    # ----- brute-force lockout ----------------------------------------------
    # Per-account, not per-IP: the IP rate limit on /auth/login is flood protection
    # and does nothing against credential stuffing from many addresses. The lockout
    # ESCALATES rather than being permanent — a permanent lock would let anyone who
    # knows an email deny that user access forever.
    LOGIN_MAX_ATTEMPTS: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5") or "5")
    LOGIN_LOCKOUT_MINUTES: int = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15") or "15")

    # ----- database TLS ------------------------------------------------------
    # Path to a CA bundle used to VERIFY the database certificate. Leave empty to
    # use the bundled Supabase root (backend/certs/). Set it when Supabase rotates
    # its root, or when pointing at a different managed Postgres.
    # Verification used to be disabled outright, which encrypted the link but
    # authenticated nothing.
    DB_SSL_ROOT_CERT: str = os.getenv("DB_SSL_ROOT_CERT", "")

    # ----- schema management -------------------------------------------------
    # True = create/patch the schema at every boot (create_all + idempotent ALTERs).
    # Convenient locally, but it keeps no version history, offers no rollback, and
    # races when several replicas start at once. Set to false in production and let
    # Alembic own the schema: `alembic upgrade head` as an explicit deploy step.
    DB_AUTO_SCHEMA: bool = os.getenv("DB_AUTO_SCHEMA", "true").strip().lower() not in (
        "0", "false", "no", "off"
    )
    # Business-neutral defaults. Per-tenant prompts (set from an industry
    # template at sign-up and editable in Settings) override these at call time.
    SYSTEM_PROMPT: str = os.getenv("SYSTEM_PROMPT", "You are a warm, professional AI receptionist answering inbound phone calls for a business. Your goals are to answer callers' questions using the business information provided, capture their details as a lead, and book an appointment or callback when they want one. Greet the caller, understand what they need, and collect: their full name, preferred date and time, and the reason for their enquiry. As soon as you have a date and time, call the book_appointment tool to confirm, then read the confirmation back. Use lookup_caller to recognise returning contacts. Always speak with the caller in Hindi. Keep every reply short, natural, and under two sentences.")
    INITIAL_GREETING: str = os.getenv("INITIAL_GREETING", "Greet the caller warmly, introduce yourself as the business's AI assistant, and ask how you can help them today.")

settings = Settings()
