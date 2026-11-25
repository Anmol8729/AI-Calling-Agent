"""Security regression tests for Single-Admin Login, Single-Active-Session,
Argon2id password hashing, HttpOnly + CSRF cookie auth, and backdoor removal.
"""

import inspect
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import bcrypt
import pytest

from backend.config.settings import settings
from backend.services.auth_service import (
    create_access_token,
    decode_access_token,
    get_password_hash,
    password_needs_rehash,
    session_claims,
    verify_password,
)


class TestArgon2idAndLegacyBcrypt:
    def test_new_hashes_use_argon2id_when_available(self):
        from backend.services import auth_service

        if auth_service._ARGON2_HASHER is None:
            pytest.skip("argon2-cffi not installed in current test environment")
        h = get_password_hash("Str0ng!AdminPass99")
        assert h.startswith("$argon2id$")
        assert verify_password("Str0ng!AdminPass99", h)
        assert not verify_password("WrongPass!", h)
        assert not password_needs_rehash(h)

    def test_legacy_bcrypt_still_verifies_and_flags_rehash(self):
        from backend.services import auth_service

        legacy = bcrypt.hashpw(b"Legacy!Pass123", bcrypt.gensalt()).decode("utf-8")
        assert verify_password("Legacy!Pass123", legacy)
        assert not verify_password("Wrong", legacy)
        if auth_service._ARGON2_HASHER is not None:
            assert password_needs_rehash(legacy) is True


class TestNoHardcodedBackdoor:
    def test_no_hardcoded_demo_admin_credentials_in_auth_routes(self):
        from backend.routes import auth as auth_routes

        src = inspect.getsource(auth_routes)
        assert "password123" not in src
        assert "admin@clarivo.io" not in src

    def test_demo_user_never_has_superadmin_flag(self):
        from backend.services.demo_data import DEMO_USER

        assert DEMO_USER.get("is_superadmin") is False


class TestSingleDesignatedAdminAndNoPublicSignup:
    def test_only_single_designated_admin_is_superadmin(self, monkeypatch):
        from backend.routes.auth import is_superadmin

        monkeypatch.setattr(settings, "ADMIN_EMAIL", "boss@clarivo.net.in")
        monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", "other@clarivo.net.in")
        assert is_superadmin("boss@clarivo.net.in") is True
        assert is_superadmin("BOSS@clarivo.net.in") is True
        assert is_superadmin("other@clarivo.net.in") is False
        assert is_superadmin("clinic@example.com") is False

    def test_register_and_google_block_designated_admin_creation(self):
        from backend.routes import auth as auth_routes

        reg_src = inspect.getsource(auth_routes.register)
        google_src = inspect.getsource(auth_routes.google_sign_in)
        assert "is_superadmin" in reg_src
        assert "is_superadmin" in google_src
        assert "403" in reg_src


class TestSingleActiveAdminSessionAndCookies:
    def test_session_claims_include_jti_for_rotation(self):
        class FakeUser:
            id = "11111111-1111-1111-1111-111111111111"
            role = "doctor"
            clinic_id = None
            token_version = 3

        c1 = session_claims(FakeUser())
        c2 = session_claims(FakeUser())
        assert c1["ver"] == 3
        assert c1["jti"] != c2["jti"]

    def test_admin_login_rotates_token_version_and_sets_httponly_cookie(self):
        from backend.routes import auth as auth_routes

        src = inspect.getsource(auth_routes.login)
        assert "user.token_version = old_ver + 1" in src
        assert "_set_admin_cookies" in src
        assert 'response_data["cookie_auth"] = True' in src

    def test_logout_revokes_token_version_and_clears_cookies(self):
        from backend.routes import auth as auth_routes

        src = inspect.getsource(auth_routes.logout)
        assert "user.token_version = old_ver + 1" in src
        assert "_clear_admin_cookies" in src

    def test_get_current_user_enforces_csrf_and_admin_inactivity(self):
        from backend.routes import auth as auth_routes

        src = inspect.getsource(auth_routes.get_current_user)
        assert "X-CSRF-Token" in src
        assert "secrets.compare_digest" in src
        assert "ADMIN_SESSION_IDLE_MINUTES" in src
        assert "_admin_last_activity" in src

    def test_frontend_never_stores_admin_token_in_localstorage(self):
        repo_root = Path(__file__).resolve().parents[2]
        store_src = (repo_root / "frontend" / "src" / "store" / "authStore.js").read_text(encoding="utf-8")
        api_src = (repo_root / "frontend" / "src" / "lib" / "api.js").read_text(encoding="utf-8")
        assert 'localStorage.removeItem("token")' in store_src
        assert "withCredentials: true" in api_src
        assert "X-CSRF-Token" in api_src
