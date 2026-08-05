"""Request/response schemas for authentication.

Security note on `role`: this field arrives from an UNAUTHENTICATED public
endpoint (POST /api/auth/register). It used to be a free-form `str`, so a caller
could self-assign any role — e.g. `{"role": "admin"}` passed the manager-only
checks in routes/phone_numbers.py, which gate paid actions like claiming a phone
number. Registration may now only create an account OWNER; every other role must
be granted by someone who already has authority (see SELF_SIGNUP_ROLE).
"""

import re
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

# Canonical roles, ordered most to least privileged WITHIN a tenant.
# Platform super-admin is deliberately NOT here: it is not a per-tenant role and
# is resolved separately from the SUPERADMIN_EMAILS allowlist.
#   owner  - the person who signed the business up ("Company Admin")
#   admin  - full access to the tenant, can manage staff
#   staff  - limited access, only what the owner/admin grants
TENANT_ROLES = ("owner", "admin", "staff")

# "doctor" is the legacy name for the account owner and still exists on rows
# created before this change, so it stays accepted for login/authorisation.
LEGACY_ROLES = ("doctor", "receptionist")
ALL_ROLES = TENANT_ROLES + LEGACY_ROLES

# The ONLY role a public self-signup may create. Kept as the legacy value so
# existing rows, the manager checks in routes/phone_numbers.py, and the
# teammate's Staff Panel all keep working unchanged.
SELF_SIGNUP_ROLE = "doctor"

# Minimum viable password policy. 6 characters accepted "123456" and "password".
MIN_PASSWORD_LENGTH = 10
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwertyuiop", "letmein123", "iloveyou1", "admin12345", "welcome123",
    "changeme123", "passw0rd", "qwerty12345", "abc12345678",
}


def validate_password_strength(value: str) -> str:
    """Reject passwords that are trivially guessable.

    Requires length + a mix of character classes, and blocks a small list of
    well-known choices. Deliberately not a full breach-corpus check — that needs
    an external service (e.g. HaveIBeenPwned k-anonymity API).
    """
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if value.lower() in _COMMON_PASSWORDS:
        raise ValueError("That password is too common. Please choose a less predictable one")
    classes = sum(
        bool(re.search(pattern, value))
        for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    )
    if classes < 3:
        raise ValueError(
            "Password must combine at least three of: lowercase, uppercase, "
            "numbers, symbols"
        )
    return value


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    # Accepted for backward compatibility with existing clients, but IGNORED:
    # the route always creates SELF_SIGNUP_ROLE. Anything else is rejected
    # outright rather than silently downgraded, so a caller attempting straight
    # privilege escalation gets a clear 422 instead of a surprising account.
    role: Literal["doctor", "owner"] = SELF_SIGNUP_ROLE
    clinic_name: Optional[str] = Field(default=None, max_length=255)
    did: Optional[str] = Field(default=None, max_length=32)
    industry: Optional[str] = Field(default=None, max_length=50)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class UserLogin(BaseModel):
    email: EmailStr
    # No strength rules here: an existing password must still be able to log in
    # even if the policy has since been tightened. Length cap only, to bound the
    # bcrypt work an unauthenticated caller can trigger.
    password: str = Field(..., max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    name: str
    clinic_id: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    clinic_id: Optional[str] = None
