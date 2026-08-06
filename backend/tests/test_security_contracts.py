"""Security regression tests.

Every case here corresponds to a hole that was found in this codebase and fixed.
They exist so the fix cannot be silently undone by a later refactor — which is the
one thing the previous test suite (11 tests over helpers and a regex) could not do
for a multi-tenant product.

Deliberately DB-free so they run in CI without production credentials. The
tenant-isolation checks that need a database live in
test_tenant_isolation_integration.py and skip themselves when DATABASE_URL is unset.
"""

import pytest

from backend.services import audit, plans, login_guard


# --------------------------------------------------------------------------
# Privilege escalation via public self-signup
# --------------------------------------------------------------------------
class TestSignupCannotEscalate:
    """`POST /api/auth/register` is public and used to accept any `role` string.

    A caller could self-assign `role: "admin"`, which passed the manager-only checks
    guarding paid actions like claiming a phone number.
    """

    @pytest.mark.parametrize("role", ["admin", "superadmin", "staff", "owner', DROP--", ""])
    def test_privileged_roles_are_rejected(self, role):
        from pydantic import ValidationError

        from backend.schemas.auth import UserRegister

        with pytest.raises(ValidationError):
            UserRegister(
                email="probe@clarivo-test.dev",
                password="Str0ng!Passw0rd",
                name="probe",
                role=role,
            )

    def test_default_role_is_the_self_signup_role(self):
        from backend.schemas.auth import SELF_SIGNUP_ROLE, UserRegister

        user = UserRegister(
            email="probe@clarivo-test.dev", password="Str0ng!Passw0rd", name="probe"
        )
        assert user.role == SELF_SIGNUP_ROLE

    def test_route_ignores_the_submitted_role_entirely(self):
        """Defence in depth: the handler must not read `payload.role`.

        The schema already restricts it, but the role has to be decided
        server-side so a future schema change cannot reopen the hole.
        """
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.register)
        assert "payload.role" not in source, (
            "register() must not read the role from the request body"
        )
        assert "role = SELF_SIGNUP_ROLE" in source


# --------------------------------------------------------------------------
# Password policy
# --------------------------------------------------------------------------
class TestPasswordPolicy:
    """`min_length=6` accepted "123456" and "password"."""

    @pytest.mark.parametrize(
        "weak",
        ["123456", "password", "abcdefghij", "PASSWORD123", "1234567890", "password123"],
    )
    def test_weak_passwords_rejected(self, weak):
        from backend.schemas.auth import validate_password_strength

        with pytest.raises(ValueError):
            validate_password_strength(weak)

    @pytest.mark.parametrize("strong", ["Str0ng!Passw0rd", "correct-horse-Battery9", "Xk9$mQ2wLp8z"])
    def test_strong_passwords_accepted(self, strong):
        from backend.schemas.auth import validate_password_strength

        assert validate_password_strength(strong) == strong

    def test_policy_applies_to_change_and_reset_too(self):
        """A policy enforced only at signup leaves every other path open."""
        from pydantic import ValidationError

        from backend.routes.auth import ChangePassword, ResetPassword

        with pytest.raises(ValidationError):
            ChangePassword(current_password="whatever", new_password="123456")
        with pytest.raises(ValidationError):
            ResetPassword(token="t" * 20, new_password="password")


# --------------------------------------------------------------------------
# XML injection on the public inbound webhook
# --------------------------------------------------------------------------
class TestInboundWebhookInjection:
    """`/api/calls/twiml/inbound` is unauthenticated and its input was interpolated
    raw into an XML response, letting a caller inject <Dial> (toll fraud)."""

    ATTACK = "</Stream><Say>hacked</Say><Dial>+919999999999</Dial><Stream>"

    def test_generated_xml_contains_no_injected_verbs(self):
        from backend.integrations.vobiz.client import VobizClient

        xml = VobizClient.get_stream_xml(f"wss://h/media-stream?destination={self.ATTACK}")
        assert "<Dial>" not in xml
        assert "<Say>" not in xml

    def test_ampersand_is_escaped(self):
        """An unescaped `&` also made the document malformed."""
        from backend.integrations.vobiz.client import VobizClient

        xml = VobizClient.get_stream_xml("wss://h/media-stream?a=1&b=2")
        assert "&amp;" in xml

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("+918065480571", "+918065480571"),
            ("918065480571", "918065480571"),
            ("</Stream><Dial>+91999</Dial>", "91999"),   # salvaged digits only
            ("'; DROP TABLE users;--", ""),
            ("javascript:alert(1)", ""),
            ("", ""),
        ],
    )
    def test_webhook_input_is_allow_listed_to_phone_shapes(self, value, expected):
        from backend.routes.calls import _safe_number

        assert _safe_number(value) == expected


# --------------------------------------------------------------------------
# Agent per-call token scoping (cross-tenant access)
# --------------------------------------------------------------------------
class TestAgentCallTokenScoping:
    """One shared secret guarded nine endpoints that each read `clinic_id` from the
    request body, making that secret a master key over every tenant's data."""

    CLINIC_A = "11111111-1111-1111-1111-111111111111"
    CLINIC_B = "22222222-2222-2222-2222-222222222222"

    @pytest.fixture(autouse=True)
    def _secret(self, monkeypatch):
        from backend.config.settings import settings

        monkeypatch.setattr(settings, "AGENT_INTERNAL_SECRET", "test-agent-secret-value", raising=False)
        monkeypatch.setattr(settings, "AGENT_CALL_TOKEN_TTL_MIN", 45, raising=False)

    def test_token_carries_its_clinic_and_call(self):
        from backend.services.call_tokens import mint_call_token, verify_call_token

        claims = verify_call_token(mint_call_token(self.CLINIC_A, "call_1"))
        assert claims["clinic_id"] == self.CLINIC_A
        assert claims["call_id"] == "call_1"
        assert claims["scope"] == "agent-call"

    def test_a_tampered_token_is_refused(self):
        from backend.services.call_tokens import mint_call_token, verify_call_token

        token = mint_call_token(self.CLINIC_A, "call_1")
        assert verify_call_token(token[:-4] + "AAAA") is None

    def test_swapping_the_clinic_requires_forging_the_signature(self):
        """The clinic lives inside the signed payload, so it cannot be substituted."""
        import base64
        import json

        from backend.services.call_tokens import mint_call_token, verify_call_token

        token = mint_call_token(self.CLINIC_A, "call_1")
        header, payload, sig = token.split(".")
        raw = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        raw["clinic_id"] = self.CLINIC_B
        forged = base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=")
        assert verify_call_token(f"{header}.{forged}.{sig}") is None

    def test_a_user_session_token_is_not_a_call_token(self):
        """The two are signed with different keys and must not be interchangeable."""
        from backend.services.auth_service import create_access_token
        from backend.services.call_tokens import verify_call_token

        session = create_access_token({"sub": "u1", "role": "admin", "clinic_id": self.CLINIC_A})
        assert verify_call_token(session) is None

    def test_a_call_token_is_not_a_user_session(self):
        from backend.services.auth_service import decode_access_token
        from backend.services.call_tokens import mint_call_token

        token = mint_call_token(self.CLINIC_A, "call_1")
        # Different signing key, so it must not decode as a session at all.
        assert decode_access_token(token) is None

    def test_nothing_is_issued_without_the_agent_secret(self, monkeypatch):
        from backend.config.settings import settings
        from backend.services.call_tokens import mint_call_token

        monkeypatch.setattr(settings, "AGENT_INTERNAL_SECRET", "", raising=False)
        assert mint_call_token(self.CLINIC_A, "call_1") is None

    def test_the_agent_secret_no_longer_falls_back_to_jwt_secret(self):
        """That fallback reused the session-signing key as an API credential."""
        import inspect

        from backend.routes import calls as calls_routes

        source = inspect.getsource(calls_routes._agent_secret_ok)
        # Strip the docstring and comments: they *explain* the removed fallback, so a
        # naive substring check would match the explanation rather than live code.
        body = "\n".join(
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        )
        if '"""' in body:
            head, _, rest = body.partition('"""')
            _doc, _, tail = rest.partition('"""')
            body = head + tail
        assert "settings.JWT_SECRET" not in body, (
            "the agent secret must not fall back to the session signing key"
        )
        assert "compare_digest" in body, "the secret must be compared in constant time"

    def test_agent_request_schemas_no_longer_accept_a_clinic_id(self):
        """If the field comes back, the body can choose the tenant again."""
        from backend.routes.calls import (
            AgentAvailabilityRequest,
            AgentBookRequest,
            AgentCallStartRequest,
            AgentPatientRequest,
            AgentPhoneRequest,
        )

        for model in (
            AgentBookRequest,
            AgentPhoneRequest,
            AgentPatientRequest,
            AgentAvailabilityRequest,
            AgentCallStartRequest,
        ):
            assert "clinic_id" not in model.model_fields, (
                f"{model.__name__} must not accept clinic_id from the request body"
            )


# --------------------------------------------------------------------------
# Session revocation
# --------------------------------------------------------------------------
class TestSessionRevocation:
    """Tokens were stateless with no version claim, so logout was browser-only and a
    stolen token stayed valid through a password reset."""

    def test_session_claims_include_the_token_version(self):
        from backend.services.auth_service import session_claims

        class FakeUser:
            id = "11111111-1111-1111-1111-111111111111"
            role = "doctor"
            clinic_id = None
            token_version = 7

        assert session_claims(FakeUser())["ver"] == 7

    def test_a_token_without_ver_reads_as_version_zero(self):
        """Tokens minted before the column existed must not log everyone out."""
        from backend.services.auth_service import create_access_token, decode_access_token

        payload = decode_access_token(create_access_token({"sub": "u1"}))
        assert int(payload.get("ver", 0) or 0) == 0

    def test_get_current_user_checks_version_and_active_flag(self):
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.get_current_user)
        assert "token_version" in source
        assert "is_active" in source
        assert 'payload.get("scope")' in source, (
            "a scoped agent token must not authenticate a dashboard user"
        )
        assert 'pop("password_hash"' in source, (
            "the password hash must not travel on the request-scoped user"
        )

    def test_password_change_and_reset_bump_the_version(self):
        import inspect

        from backend.routes import auth as auth_routes

        for fn in (auth_routes.change_password, auth_routes.reset_password):
            assert "token_version" in inspect.getsource(fn), (
                f"{fn.__name__} must invalidate existing sessions"
            )


# --------------------------------------------------------------------------
# Brute-force lockout
# --------------------------------------------------------------------------
class TestLoginLockout:
    """An IP-keyed rate limit does nothing against credential stuffing from a pool
    of addresses, and resets on every deploy."""

    def test_lockout_escalates_and_is_capped(self):
        from backend.config.settings import settings

        base = settings.LOGIN_LOCKOUT_MINUTES
        threshold = settings.LOGIN_MAX_ATTEMPTS
        first = login_guard.lockout_for(threshold).total_seconds() / 60
        second = login_guard.lockout_for(threshold + 1).total_seconds() / 60
        assert first == base
        assert second > first, "repeat offenders must wait longer"
        # Capped, because a permanent lock lets anyone who knows an email deny that
        # user access forever.
        assert login_guard.lockout_for(threshold + 50).total_seconds() / 60 <= 120

    def test_failures_accumulate_then_lock(self):
        from backend.config.settings import settings

        class FakeUser:
            email = "probe@clarivo-test.dev"
            failed_login_attempts = 0
            locked_until = None
            last_login_at = None

        user = FakeUser()
        for _ in range(settings.LOGIN_MAX_ATTEMPTS - 1):
            assert login_guard.register_failure(user) is False
        assert login_guard.register_failure(user) is True
        assert login_guard.is_locked(user) is True

    def test_a_successful_sign_in_clears_the_counter(self):
        from datetime import datetime, timedelta

        class FakeUser:
            email = "probe@clarivo-test.dev"
            failed_login_attempts = 4
            locked_until = datetime.utcnow() + timedelta(minutes=5)
            last_login_at = None

        user = FakeUser()
        login_guard.register_success(user)
        assert user.failed_login_attempts == 0
        assert user.locked_until is None
        assert user.last_login_at is not None

    def test_login_does_not_leak_which_emails_exist(self):
        """Identical message AND comparable timing for an unknown address."""
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.login)
        assert "_DUMMY_PASSWORD_HASH" in source, (
            "an unknown email must still pay the bcrypt cost, or timing reveals it"
        )
        # One shared response object for every rejection path.
        assert source.count("Invalid email or password") == 1


# --------------------------------------------------------------------------
# Spend controls
# --------------------------------------------------------------------------
class TestNumberProvisioningCap:
    """Provisioning was uncapped for every plan, including the free trial, while each
    DID costs roughly Rs100 setup plus Rs500/month."""

    def test_every_plan_declares_a_number_allowance(self):
        for plan in plans.list_plans():
            assert plan.get("included_numbers", 0) >= 1, plan["key"]

    def test_the_trial_is_limited_to_one(self):
        assert plans.included_numbers("free") == 1

    def test_higher_plans_allow_more(self):
        assert plans.included_numbers("scale") > plans.included_numbers("free")

    def test_an_unknown_plan_falls_back_to_the_most_restrictive(self):
        assert plans.included_numbers("not-a-plan") == plans.included_numbers(
            plans.DEFAULT_PLAN_KEY
        )

    def test_a_per_tenant_override_wins(self):
        assert plans.included_numbers("free", 9) == 9

    def test_the_cap_is_checked_before_the_provider_is_contacted(self):
        import inspect

        from backend.routes import phone_numbers

        source = inspect.getsource(phone_numbers.provision_number)
        quota_at = source.index("_number_quota")
        api_at = source.index("VobizNumbersAPI")
        assert quota_at < api_at, (
            "the plan cap must be enforced before any provider call, so a capped "
            "clinic cannot trigger a paid assignment"
        )


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------
class TestAuditTrail:
    def test_credentials_are_redacted_from_details(self):
        scrubbed = audit._scrub({
            "whatsapp_access_token": "EAAU-real-token",
            "password": "hunter2",
            "api_key": "sk-live-123",
            "authorization": "Bearer abc",
            "fields": ["knowledge_base"],
            "count": 3,
        })
        blob = str(scrubbed)
        assert "EAAU-real-token" not in blob
        assert "hunter2" not in blob
        assert "sk-live-123" not in blob
        # Non-sensitive context must survive, or the trail is useless.
        assert scrubbed["fields"] == ["knowledge_base"]
        assert scrubbed["count"] == 3

    def test_settings_audit_records_field_names_not_values(self):
        import inspect

        from backend.routes import clinics

        source = inspect.getsource(clinics.update_settings)
        assert "sorted(update_data.keys())" in source, (
            "settings updates must log field names only — the payload carries the "
            "WhatsApp token and the AI system prompt"
        )

    def test_the_tenant_timeline_is_scoped_to_the_caller(self):
        import inspect

        from backend.routes import clinics

        source = inspect.getsource(clinics.clinic_activity)
        assert 'current_user.get("clinic_id")' in source
        assert "clinic_id" in source


# --------------------------------------------------------------------------
# Startup configuration guard
# --------------------------------------------------------------------------
class TestProductionConfigGuard:
    """Booting with a default secret is worse than failing to boot: it looks healthy
    while being trivially exploitable."""

    def _problems(self, monkeypatch, **overrides):
        from backend.config.settings import settings
        from backend.middlewares import security

        safe = {
            "JWT_SECRET": "x" * 48,
            "CORS_ORIGINS": "https://app.clarivo.ai",
            "AGENT_INTERNAL_SECRET": "y" * 48,
            "APP_BASE_URL": "https://app.clarivo.ai",
            "SMTP_HOST": "smtp.example.com",
            "DB_AUTO_SCHEMA": False,
        }
        safe.update(overrides)
        for key, value in safe.items():
            monkeypatch.setattr(settings, key, value, raising=False)
        return " | ".join(security.check_production_config())

    def test_a_healthy_configuration_reports_nothing(self, monkeypatch):
        # DB TLS / limiter checks read live module state, so ignore those two here.
        problems = self._problems(monkeypatch)
        for phrase in ("JWT_SECRET", "CORS_ORIGINS", "APP_BASE_URL", "SMTP", "DB_AUTO_SCHEMA"):
            assert phrase not in problems, problems

    def test_the_shipped_default_secret_is_caught(self, monkeypatch):
        from backend.middlewares.security import INSECURE_JWT_DEFAULT

        assert "JWT_SECRET" in self._problems(monkeypatch, JWT_SECRET=INSECURE_JWT_DEFAULT)

    def test_a_short_secret_is_caught(self, monkeypatch):
        assert "JWT_SECRET" in self._problems(monkeypatch, JWT_SECRET="tooshort")

    def test_wildcard_cors_is_caught(self, monkeypatch):
        assert "CORS_ORIGINS" in self._problems(monkeypatch, CORS_ORIGINS="*")

    def test_localhost_cors_is_caught(self, monkeypatch):
        assert "CORS_ORIGINS" in self._problems(
            monkeypatch, CORS_ORIGINS="https://app.clarivo.ai,http://localhost:3000"
        )

    def test_reusing_the_jwt_secret_for_the_agent_is_caught(self, monkeypatch):
        shared = "z" * 48
        problems = self._problems(monkeypatch, JWT_SECRET=shared, AGENT_INTERNAL_SECRET=shared)
        assert "AGENT_INTERNAL_SECRET" in problems

    def test_a_missing_agent_secret_is_caught(self, monkeypatch):
        assert "AGENT_INTERNAL_SECRET" in self._problems(monkeypatch, AGENT_INTERNAL_SECRET="")

    def test_plain_http_base_url_is_caught(self, monkeypatch):
        assert "APP_BASE_URL" in self._problems(monkeypatch, APP_BASE_URL="http://app.clarivo.ai")

    def test_missing_smtp_is_caught(self, monkeypatch):
        """Without email, verification cannot gate the allowlisted superadmin."""
        assert "SMTP" in self._problems(monkeypatch, SMTP_HOST="")

    def test_boot_time_schema_rewriting_is_caught(self, monkeypatch):
        assert "DB_AUTO_SCHEMA" in self._problems(monkeypatch, DB_AUTO_SCHEMA=True)


# --------------------------------------------------------------------------
# The removed unauthenticated media pipeline
# --------------------------------------------------------------------------
class TestLegacyMediaStreamRemoved:
    """It accepted anonymous WebSocket connections, chose a tenant from a query
    parameter, spent real TTS/LLM credit, and wrote call rows into that tenant."""

    def test_the_route_is_gone(self):
        from backend.websocket import handler

        assert not hasattr(handler, "handle_media_stream")

    def test_no_route_named_media_stream_is_mounted(self):
        # This FastAPI version wraps included routers, so app.routes does not expose
        # child paths — read the websocket router itself.
        from backend.websocket.handler import router

        paths = {getattr(r, "path", "") for r in router.routes}
        assert "/media-stream" not in paths, paths

    def test_the_notification_socket_still_exists_and_is_guarded(self):
        import inspect

        from backend.websocket import handler

        paths = {getattr(r, "path", "") for r in handler.router.routes}
        assert "/ws/notifications" in paths, paths
        source = inspect.getsource(handler.notifications_ws)
        assert "decode_access_token" in source
        assert 'payload.get("scope")' in source, (
            "an agent call token must not open a dashboard stream"
        )

    def test_the_legacy_llm_modules_are_gone(self):
        for module in (
            "backend.integrations.minimax.llm",
            "backend.integrations.minimax.stt",
            "backend.integrations.minimax.tts",
        ):
            with pytest.raises(ImportError):
                __import__(module)


# --------------------------------------------------------------------------
# Stale call cleanup
# --------------------------------------------------------------------------
class TestStaleCallSweeper:
    """A crashed agent left calls `active` with `duration: 0` forever, so the live
    view showed calls that never end and average duration was dragged to zero."""

    def test_duration_comes_from_the_last_turn_not_from_now(self):
        import inspect

        from backend.services import repository

        source = inspect.getsource(repository.close_stale_calls)
        assert "last_activity_at" in source
        assert "row.status = \"failed\"" in source, (
            "a call with no transcript at all should not be reported as completed"
        )

    def test_transcript_writes_stamp_the_activity_time(self):
        import inspect

        from backend.services import repository

        assert "last_activity_at" in inspect.getsource(repository.append_transcript)


# --------------------------------------------------------------------------
# Google sign-in via Supabase Auth
# --------------------------------------------------------------------------
class TestGoogleSignIn:
    """Supabase Auth is used ONLY to establish a Google identity.

    The danger in bolting on a second identity source is that it becomes a way to
    walk around the first one's rules. These pin the checks that prevent that.
    """

    def test_the_service_role_key_is_never_read(self):
        """It bypasses RLS entirely and must not exist anywhere in the backend."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        offenders = []
        for path in root.rglob("*.py"):
            if "__pycache__" in str(path) or path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "SERVICE_ROLE" in text.upper() and "never" not in text.lower():
                offenders.append(str(path.relative_to(root)))
        assert not offenders, f"service role key referenced in: {offenders}"

    def test_token_verification_delegates_to_supabase(self):
        """Hand-rolled JWT verification is where auth bypasses come from.

        Local verification would mean fetching JWKS, picking a key and allow-listing
        algorithms — accepting `alg: none` or falling back to HS256 with a public
        value are classic critical findings. Supabase's own endpoint cannot be got
        wrong from here.
        """
        import inspect

        from backend.services import supabase_auth

        source = inspect.getsource(supabase_auth)
        assert "/auth/v1/user" in source
        assert "jwt.decode" not in source, (
            "tokens must be validated by Supabase, not decoded locally"
        )

    def test_only_google_identities_are_accepted(self):
        """Otherwise a Supabase email/password account becomes a way to obtain an app
        session while skipping our own sign-up rules."""
        import inspect

        from backend.services import supabase_auth

        source = inspect.getsource(supabase_auth.verify_google_token)
        assert "is_google" in source
        assert "email_confirmed" in source, (
            "the email is the key accounts are matched on, so it must be confirmed"
        )

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ({"app_metadata": {"provider": "google"}}, True),
            ({"app_metadata": {"providers": ["google"]}}, True),
            ({"app_metadata": {"provider": "email"}}, False),
            ({"app_metadata": {"provider": "github"}}, False),
            ({}, False),
        ],
    )
    def test_provider_detection(self, raw, expected):
        from backend.services.supabase_auth import SupabaseIdentity

        assert SupabaseIdentity(raw).is_google is expected

    def test_identity_normalises_googles_metadata_keys(self):
        """Google supplies the name and picture under different keys per flow."""
        from backend.services.supabase_auth import SupabaseIdentity

        a = SupabaseIdentity({
            "id": "abc", "email": "Person@Example.com",
            "email_confirmed_at": "2026-01-01T00:00:00Z",
            "user_metadata": {"full_name": "A Person", "avatar_url": "http://img/a"},
            "app_metadata": {"provider": "google"},
        })
        assert a.email == "person@example.com", "email must be normalised for matching"
        assert a.full_name == "A Person"
        assert a.avatar_url == "http://img/a"
        assert a.email_confirmed is True

        b = SupabaseIdentity({
            "id": "def", "email": "b@example.com",
            "user_metadata": {"name": "B Person", "picture": "http://img/b"},
            "app_metadata": {"providers": ["google"]},
        })
        assert b.full_name == "B Person"
        assert b.avatar_url == "http://img/b"
        assert b.email_confirmed is False, "no confirmation timestamp means unconfirmed"

    @pytest.mark.asyncio
    async def test_nothing_is_trusted_when_unconfigured(self, monkeypatch):
        """With no anon key the endpoint must refuse, not accept an unverified token."""
        from backend.config.settings import settings
        from backend.services.supabase_auth import SupabaseAuthError, verify_google_token

        monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "", raising=False)
        monkeypatch.setattr(settings, "SUPABASE_URL", "", raising=False)
        monkeypatch.setattr(settings, "DB_USER", "postgres", raising=False)
        with pytest.raises(SupabaseAuthError):
            await verify_google_token("any.token.here")

    def test_the_role_is_not_taken_from_the_request(self):
        """The same rule as password signup: privilege is never client-supplied."""
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.google_sign_in)
        assert "role=SELF_SIGNUP_ROLE" in source
        assert "payload.role" not in source

    def test_suspended_accounts_cannot_sign_in_with_google(self):
        """A second door must not bypass suspension."""
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.google_sign_in)
        assert "is_active" in source

    def test_google_signin_returns_our_own_session_token(self):
        """The Supabase token must not become the app session — every downstream
        control (tenant scoping, revocation, roles) keys off ours."""
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.google_sign_in)
        assert "create_access_token(session_claims(" in source

    def test_google_accounts_cannot_be_password_logged_in(self):
        """They have no password. The check must also not become a timing oracle for
        which accounts are Google-only."""
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.login)
        assert "if not user.password_hash:" in source
        assert source.count("_DUMMY_PASSWORD_HASH") >= 2, (
            "the passwordless branch must also pay the bcrypt cost"
        )

    def test_password_hash_is_nullable(self):
        """A placeholder hash would be indistinguishable from a real one."""
        from backend.models import User

        assert User.__table__.c.password_hash.nullable is True

    def test_one_google_identity_cannot_map_to_two_accounts(self):
        from backend.models import User

        assert User.__table__.c.supabase_user_id.unique is True

    def test_the_profile_fields_exist_on_users(self):
        """The profile contract, mapped onto the existing table rather than a second
        one that would duplicate name/email/role."""
        from backend.models import User

        for column in ("id", "name", "email", "avatar_url", "role", "created_at", "updated_at"):
            assert column in User.__table__.c, f"missing profile field {column}"


class TestNewAccountIsNotBornSuspended:
    """Regression: every brand new Google account was reported as suspended.

    A model `default=` is applied when the row is INSERTed, not when the Python
    object is constructed. So immediately after `User(...)` the flag is still None,
    and the guard — written as `not bool(getattr(user, "is_active", True))` — read
    None as False and therefore as "suspended". The `getattr` default never applied,
    because the attribute existed; it was simply None.

    The result was that Google sign-in worked, verified the identity, created the
    account, and then refused it. Worse, the audit write for that refusal failed
    silently (its clinic_id referenced a tenant in the same uncommitted transaction),
    so the only trace was the message on screen.
    """

    def test_a_freshly_constructed_user_has_no_flag_value_yet(self):
        """The behaviour that made the original guard wrong. If SQLAlchemy ever
        changes this, the test says so instead of the bug quietly reappearing."""
        from backend.models import User

        fresh = User(email="x@y.z", name="x", role="doctor")
        assert fresh.is_active is None, (
            "column defaults apply at INSERT, so this is None until flush"
        )
        # And this is precisely why a falsy check was wrong:
        assert not bool(fresh.is_active) is True

    def test_the_guard_only_treats_explicit_false_as_suspended(self):
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.google_sign_in)
        assert 'is_active", True) is False' in source, (
            "must compare against False explicitly; a falsy test also catches None"
        )
        assert "not bool(getattr(user" not in source

    def test_new_accounts_set_their_flags_explicitly(self):
        """Belt and braces alongside the guard: do not depend on default timing."""
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.google_sign_in)
        assert "is_active=True" in source
        assert "await db.flush()" in source, (
            "flush before the checks so persisted defaults are in place"
        )

    def test_password_signup_is_unaffected(self):
        """/register never had this bug — it relies on the INSERT default and never
        inspects the flag before commit. Pinned so a 'consistency' refactor does not
        introduce the same mistake there."""
        import inspect

        from backend.routes import auth as auth_routes

        source = inspect.getsource(auth_routes.register)
        assert "is_active" not in source


# --------------------------------------------------------------------------
# Staff role boundary (merged from the teammate's Staff Panel work)
# --------------------------------------------------------------------------
class TestStaffRoleBoundary:
    """Staff are read-mostly members of one tenant.

    The dashboard hides Setup, Billing and Admin from them, but a hidden menu item
    is not access control — the API has to say no as well. These pin the server-side
    half so a UI change cannot quietly become the only thing standing in the way.
    """

    def _guard_of(self, fn) -> str:
        import inspect

        return inspect.getsource(fn)

    def test_staff_cannot_edit_or_delete_contacts(self):
        from backend.routes import patients

        assert "require_non_staff" in self._guard_of(patients.update_patient)
        assert "require_non_staff" in self._guard_of(patients.delete_patient)

    def test_staff_can_still_read_and_create_contacts(self):
        """Deliberate: a receptionist has to be able to add a walk-in."""
        from backend.routes import patients

        assert "require_non_staff" not in self._guard_of(patients.list_patients)
        assert "require_non_staff" not in self._guard_of(patients.create_patient)

    def test_staff_cannot_cancel_or_move_bookings(self):
        """Cancelling and rescheduling are owner actions.

        All three matter, not just DELETE:
          * `update_appointment` takes `status`, so `status="cancelled"` through PUT
            would cancel a booking without ever touching DELETE.
          * `reschedule_appointment` can move a booking to an arbitrary date, which
            is functionally the same as cancelling it.
        Guarding only DELETE would leave both bypasses open.
        """
        from backend.routes import appointments

        for fn in (
            appointments.cancel_appointment,
            appointments.update_appointment,
            appointments.reschedule_appointment,
        ):
            assert "require_non_staff" in self._guard_of(fn), fn.__name__

    def test_staff_can_still_read_and_create_bookings(self):
        """A receptionist has to be able to book a walk-in and see the day's list."""
        from backend.routes import appointments

        assert "require_non_staff" not in self._guard_of(appointments.list_appointments)
        assert "require_non_staff" not in self._guard_of(appointments.create_appointment)

    def test_destructive_record_actions_are_audited(self):
        """A hard-deleted contact cannot be recovered, so the trail is the only
        record that it existed. Cancellations get disputed, so they need an actor."""
        from backend.routes import appointments, patients

        assert "audit.record" in self._guard_of(patients.delete_patient)
        assert "audit.record" in self._guard_of(appointments.cancel_appointment)

    def test_patient_delete_captures_identity_before_the_row_is_gone(self):
        """Reading patient.name after db.delete() would audit an empty record."""
        source = self._guard_of(__import__(
            "backend.routes.patients", fromlist=["delete_patient"]
        ).delete_patient)
        detail_line = source.index("deleted = {")
        delete_line = source.index("await db.delete(patient)")
        assert detail_line < delete_line, "capture the fields before deleting the row"

    def test_staff_cannot_change_business_settings(self):
        """This payload carries the AI system prompt, the knowledge base and the
        WhatsApp access token. It was reachable by staff even though the UI hid it."""
        from backend.routes import clinics

        assert "require_non_staff" in self._guard_of(clinics.update_settings)

    def test_staff_cannot_spend_money(self):
        from backend.routes import billing

        for fn in (billing.checkout, billing.verify_payment, billing.request_upgrade):
            assert "require_non_staff" in self._guard_of(fn), fn.__name__

    def test_staff_cannot_create_more_staff(self):
        """Otherwise the role is self-propagating and the boundary is meaningless."""
        from backend.routes import auth as auth_routes

        source = self._guard_of(auth_routes.create_staff)
        assert 'require_roles(["doctor"])' in source

    def test_staff_creation_is_tenant_scoped(self):
        """clinic_id from the CALLER, never the payload, or one owner could plant an
        account inside another tenant."""
        from backend.routes import auth as auth_routes

        source = self._guard_of(auth_routes.create_staff)
        assert 'current_user.get("clinic_id")' in source
        assert "payload.clinic_id" not in source

    def test_staff_role_is_hardcoded_not_client_supplied(self):
        from backend.routes import auth as auth_routes

        source = self._guard_of(auth_routes.create_staff)
        assert 'role="staff"' in source
        assert "payload.role" not in source

    def test_staff_passwords_obey_the_same_policy_as_everyone_else(self):
        """It shipped with min_length=6, which would have made staff accounts the one
        place a two-second password was acceptable."""
        from pydantic import ValidationError

        from backend.routes.auth import StaffCreate

        for weak in ("123456", "password", "abcdefghij"):
            with pytest.raises(ValidationError):
                StaffCreate(name="S", email="s@example.com", password=weak)
        # A compliant one still works.
        assert StaffCreate(name="S", email="s@example.com", password="Str0ng!Passw0rd")

    def test_creating_a_staff_account_is_audited(self):
        """Creating a login into a tenant's patient data must be attributable."""
        from backend.routes import auth as auth_routes

        assert "audit.record" in self._guard_of(auth_routes.create_staff)

    def test_the_frontend_guard_admits_it_is_only_cosmetic(self):
        """A guard that looks authoritative but is not is worse than none, because
        the next person trusts it."""
        import pathlib

        guard = (
            pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "src" / "components" / "StaffRoute.jsx"
        )
        text = guard.read_text(encoding="utf-8", errors="ignore")
        assert "backend still enforces" in text.lower() or "keeps the ui honest" in text.lower()


class TestPatientProvenance:
    """`patients.source` / `created_by`, merged from the Staff Panel work.

    They arrived with a schema.sql entry but no migration. schema.sql is not executed
    by the application and `create_all` does not ALTER an existing table, so the
    columns were missing from the live database while the code already wrote to them.
    """

    def test_the_columns_exist_on_the_model(self):
        from backend.models import Patient

        assert "source" in Patient.__table__.c
        assert "created_by" in Patient.__table__.c

    def test_source_has_a_server_default_so_existing_rows_survive_the_alter(self):
        """NOT NULL added to a populated table needs a value for the rows already
        there, or the migration aborts."""
        from backend.models import Patient

        assert Patient.__table__.c.source.nullable is False
        assert Patient.__table__.c.source.server_default is not None

    def test_deleting_a_user_does_not_delete_their_patients(self):
        from backend.models import Patient

        fks = list(Patient.__table__.c.created_by.foreign_keys)
        assert fks, "created_by should reference users.id"
        assert fks[0].ondelete == "SET NULL"
