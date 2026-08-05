"""Verifies a Supabase access token, for Google sign-in only.

Scope
-----
Supabase Auth is used here as a Google identity provider and nothing more. It does
not own sessions, passwords, verification, revocation, lockout or roles — those stay
in `public.users` and `backend/routes/auth.py`, where they are already implemented,
hardened and test-covered. This module answers exactly one question: *"who does
Supabase say this token belongs to?"*

Why the token is verified by calling Supabase, not by decoding it locally
------------------------------------------------------------------------
Local verification would mean fetching the project's JWKS, selecting the right key,
and allow-listing algorithms. Every one of those is a place where a mistake becomes a
**full authentication bypass** — accepting `alg: none`, trusting an attacker-supplied
`kid`, or falling back to HS256 with a public value as the secret are all classic
findings. Supabase's own `/auth/v1/user` endpoint performs that validation and cannot
be got wrong from here.

The cost is one HTTPS round trip per sign-in. Sign-in is rare (not a per-request
path), so that is a good trade for removing a class of critical bug.

What is checked, and why each check matters
-------------------------------------------
1. The token is accepted by Supabase (proves it is genuine and unexpired).
2. The identity came from **Google**, not from Supabase email/password — otherwise
   anyone could self-register in Supabase Auth and use this endpoint to obtain an
   application session, bypassing our own sign-up rules entirely.
3. Google confirmed the email address. The email is what we match an existing
   account on, so an unconfirmed one would let someone claim another user's account.
"""

import logging
from typing import Optional

import httpx

from backend.config.settings import settings

logger = logging.getLogger("supabase-auth")

# Sign-in should not hang on a slow provider; the caller surfaces a clean error.
_TIMEOUT = 12.0


class SupabaseIdentity:
    """A verified Google identity, normalised for our own user record."""

    def __init__(self, raw: dict):
        self.supabase_user_id: str = str(raw.get("id") or "")
        self.email: str = (raw.get("email") or "").strip().lower()
        self.email_confirmed: bool = bool(
            raw.get("email_confirmed_at") or raw.get("confirmed_at")
        )
        meta = raw.get("user_metadata") or {}
        # Google populates these under different keys depending on the flow.
        self.full_name: str = (
            meta.get("full_name") or meta.get("name") or ""
        ).strip()
        self.avatar_url: str = (
            meta.get("avatar_url") or meta.get("picture") or ""
        ).strip()
        app_meta = raw.get("app_metadata") or {}
        providers = app_meta.get("providers") or []
        self.provider: str = (app_meta.get("provider") or "").strip().lower()
        self.providers = [str(p).strip().lower() for p in providers]

    @property
    def is_google(self) -> bool:
        return self.provider == "google" or "google" in self.providers

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SupabaseIdentity {self.email} provider={self.provider}>"


class SupabaseAuthError(Exception):
    """Raised when a token cannot be verified or the identity is unusable."""


async def verify_google_token(access_token: str) -> SupabaseIdentity:
    """Return the verified Google identity behind `access_token`.

    Raises SupabaseAuthError with a message safe to show a user.
    """
    if not settings.google_oauth_enabled:
        raise SupabaseAuthError(
            "Google sign-in is not configured on the server."
        )
    token = (access_token or "").strip()
    if not token:
        raise SupabaseAuthError("No Google sign-in token was supplied.")

    url = f"{settings.supabase_url}/auth/v1/user"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": settings.SUPABASE_ANON_KEY.strip(),
                },
            )
    except httpx.HTTPError as e:
        logger.error(f"Could not reach Supabase Auth at {url}: {e}")
        raise SupabaseAuthError(
            "Could not reach the sign-in provider. Please try again."
        ) from e

    if response.status_code == 401:
        # Expired or forged. Deliberately vague to the caller.
        raise SupabaseAuthError("That Google sign-in has expired. Please try again.")
    if response.status_code != 200:
        logger.error(
            f"Supabase Auth returned {response.status_code} verifying a token: "
            f"{response.text[:200]}"
        )
        raise SupabaseAuthError("Google sign-in could not be verified.")

    try:
        identity = SupabaseIdentity(response.json())
    except ValueError as e:
        raise SupabaseAuthError("Google sign-in could not be verified.") from e

    if not identity.email:
        raise SupabaseAuthError(
            "Google did not share an email address with us, so an account cannot be created."
        )

    if not identity.is_google:
        # Without this, a Supabase email/password account could be used to obtain an
        # application session and skip our own sign-up rules (password policy, role
        # assignment, tenant creation).
        logger.warning(
            f"Rejected a non-Google Supabase identity for {identity.email} "
            f"(provider={identity.provider!r}, providers={identity.providers})."
        )
        raise SupabaseAuthError("This endpoint only accepts Google sign-in.")

    if not identity.email_confirmed:
        # The email is the key we match accounts on, so an unconfirmed address
        # would be a way to claim someone else's account.
        raise SupabaseAuthError("Google has not confirmed that email address.")

    return identity


def google_redirect_target() -> Optional[str]:
    """Where Supabase should send the browser back to after Google sign-in.

    Kept here so the value used in docs and the frontend has one obvious source.
    """
    base = (settings.APP_BASE_URL or "").rstrip("/")
    return f"{base}/auth/callback" if base else None
