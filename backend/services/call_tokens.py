"""Short-lived tokens that scope the voice agent to ONE call and ONE tenant.

Why this exists
---------------
The agent's internal endpoints used to share a single long-lived secret
(`X-Internal-Secret`), and each endpoint read `clinic_id` straight out of the
request body. That combination meant anything holding the secret could:

  * read ANY tenant's `system_prompt` + `knowledge_base` (their business IP)
    via `/api/calls/agent-context`,
  * write bookings and contacts into ANY tenant,
  * append transcript turns to, or close, ANY `call_id` (a plain IDOR).

So one secret was effectively a master key over every client's data — the exact
cross-tenant leak a multi-tenant product cannot ship with.

Now the shared secret only unlocks ONE bootstrap endpoint (`/agent-context`),
which resolves the tenant server-side from the dialed DID and hands back a token
bound to `(clinic_id, call_id)`. Every other agent endpoint takes the clinic from
the token's claims and ignores the body, so a token stolen mid-call is useless
against any other tenant or any other call, and expires on its own.

Key separation
--------------
These tokens are signed with a key DERIVED from `AGENT_INTERNAL_SECRET`, not with
`JWT_SECRET`. That keeps the agent's trust domain cryptographically separate from
user sessions: a leaked agent key cannot mint a user session, and a leaked
`JWT_SECRET` cannot mint a call token.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

from backend.config.settings import settings

logger = logging.getLogger("call-tokens")

_ALGORITHM = "HS256"
# Distinguishes these tokens from user sessions. Verification requires an exact
# match, so a user access token can never be replayed against an agent endpoint.
_SCOPE = "agent-call"
_DERIVATION_LABEL = b"clarivo-call-token-v1:"


def _signing_key() -> Optional[str]:
    """Key derived from AGENT_INTERNAL_SECRET, or None when it isn't configured.

    Deliberately does NOT fall back to JWT_SECRET. The old fallback meant a
    deployment that forgot to set AGENT_INTERNAL_SECRET silently reused the
    session-signing key as an API credential — so leaking it anywhere in the call
    path would let an attacker mint tokens for any user on the platform.
    """
    base = (settings.AGENT_INTERNAL_SECRET or "").strip()
    if not base:
        return None
    return hashlib.sha256(_DERIVATION_LABEL + base.encode("utf-8")).hexdigest()


def token_ttl_minutes() -> int:
    """How long a call token stays valid.

    Must comfortably outlast a real conversation (a token expiring mid-call would
    silently break booking), while staying short enough that a leaked one is of
    little use. `AGENT_SILENCE_HANGUP_SEC` bounds real calls to a few minutes.
    """
    raw = getattr(settings, "AGENT_CALL_TOKEN_TTL_MIN", 45)
    try:
        return max(int(raw), 5)
    except (TypeError, ValueError):
        return 45


def mint_call_token(clinic_id, call_id: str) -> Optional[str]:
    """Issue a token valid only for this tenant + this call. None if unconfigured."""
    key = _signing_key()
    if key is None:
        logger.error(
            "Cannot mint a call token: AGENT_INTERNAL_SECRET is not set. The voice "
            "agent will be unable to save bookings or call logs."
        )
        return None
    if not clinic_id or not call_id:
        return None
    now = datetime.now(timezone.utc)
    claims = {
        "scope": _SCOPE,
        "clinic_id": str(clinic_id),
        "call_id": str(call_id),
        "iat": now,
        "exp": now + timedelta(minutes=token_ttl_minutes()),
    }
    return jwt.encode(claims, key, algorithm=_ALGORITHM)


def verify_call_token(token: str) -> Optional[dict]:
    """Return the claims for a valid call token, else None.

    Rejects anything without the exact `agent-call` scope, so a user session
    token (signed with a different key, and carrying no scope) can never be used
    here even if the two keys were ever misconfigured to match.
    """
    key = _signing_key()
    if key is None or not token:
        return None
    try:
        claims = jwt.decode(token, key, algorithms=[_ALGORITHM])
    except JWTError:
        return None
    if claims.get("scope") != _SCOPE:
        return None
    if not claims.get("clinic_id") or not claims.get("call_id"):
        return None
    return claims
