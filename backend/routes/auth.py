import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.services.db import get_db
from backend.services.limiter import limiter
from backend.services.auth_service import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
    generate_token,
    hash_token,
    session_claims,
)
from backend.services import login_guard, audit
from backend.services.supabase_auth import SupabaseAuthError, verify_google_token
from backend.services.email import send_email
from backend.services.industry_templates import get_template
from backend.models import User, Tenant, PasswordResetToken, PhoneNumber
from backend.schemas.auth import (
    UserRegister,
    UserLogin,
    SELF_SIGNUP_ROLE,
    MIN_PASSWORD_LENGTH,
    validate_password_strength,
)
from backend.utils.helpers import api_response, serialize_model, to_uuid

logger = logging.getLogger("auth-router")

# Hashed once at import. Login runs a bcrypt comparison against this when the
# email does not exist, so a request for an unknown address costs roughly the same
# as one for a real account. Without it, response timing tells an attacker which
# addresses are registered — cheap account enumeration despite the identical
# error message.
_DUMMY_PASSWORD_HASH = get_password_hash("clarivo-timing-equaliser-not-a-real-password")
router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    # A per-call agent token must never authenticate a dashboard user. Those are
    # signed with a different key so they would fail anyway, but rejecting any
    # scoped token here keeps the two trust domains explicitly separate.
    if payload.get("scope"):
        raise credentials_exception

    user_id = to_uuid(payload.get("sub"))
    if user_id is None:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    # Suspended accounts lose access on their NEXT request, not whenever their
    # token happens to expire.
    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended. Please contact support.",
        )

    # Revocation check. Password change / reset / "log out everywhere" bump
    # token_version, which instantly invalidates every token carrying the old
    # value. Tokens minted before this column existed have no `ver` and are read
    # as 0, matching the default, so nobody is logged out by the upgrade itself.
    if int(payload.get("ver", 0) or 0) != int(getattr(user, "token_version", 0) or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session has ended. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_data = serialize_model(user)
    # Never let the hash travel with the request-scoped user, so a future handler
    # cannot leak it by returning `current_user` wholesale.
    user_data.pop("password_hash", None)
    return user_data


def require_roles(allowed_roles: list):
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user
    return role_checker


async def require_non_staff(current_user: dict = Depends(get_current_user)):
    """Dependency that blocks staff-role users from write operations.

    Staff can read but cannot create, edit, or delete patients.
    Apply this to any patient write route instead of (or alongside) the
    regular get_current_user dependency.
    """
    if current_user.get("role") == "staff":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff accounts are read-only and cannot perform this action",
        )
    return current_user


def is_superadmin(email: str) -> bool:
    """True if the email is in the platform SUPERADMIN_EMAILS allowlist."""
    allow = [e.strip().lower() for e in (settings.SUPERADMIN_EMAILS or "").split(",") if e.strip()]
    return bool(email) and email.strip().lower() in allow


async def require_superadmin(current_user: dict = Depends(get_current_user)):
    """Dependency that restricts a route to platform super-admins.

    Super-admin is granted by the SUPERADMIN_EMAILS allowlist, which on its own
    proves nothing: before email verification existed, whoever registered an
    allowlisted address FIRST became platform admin — full access to every tenant,
    no mailbox check. So a verified address is also required.

    Only enforced when email delivery is actually configured. With SMTP absent
    verification cannot be completed normally, and refusing then would lock the
    owner out of their own admin panel. `check_production_config` treats missing
    SMTP as a production blocker, so this cannot stay unenforced in production.
    """
    if not is_superadmin(current_user.get("email", "")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    if settings.SMTP_HOST and not current_user.get("email_verified_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Verify your email address before using platform admin. "
                "Check your inbox, or request a new link from /api/auth/resend-verification."
            ),
        )
    if not settings.SMTP_HOST:
        logger.warning(
            f"Super-admin access granted to {current_user.get('email')} WITHOUT an "
            "email-verification check, because SMTP_HOST is not configured. Configure "
            "SMTP before going live — the allowlist alone proves nothing."
        )
    return current_user


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, payload: UserRegister, db: AsyncSession = Depends(get_db)):
    # Check if user already exists
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        return api_response(success=False, message="Email already registered", status_code=400)

    # Defence in depth: the role is decided HERE, never taken from the request.
    # The schema already restricts the field, but this guarantees that even a
    # future schema change cannot turn public signup into a way to mint a
    # privileged account. Staff/admin accounts are created by an authenticated
    # owner, not by self-signup.
    role = SELF_SIGNUP_ROLE

    # Create Tenant (the client's business) first, when applicable.
    clinic_id = None
    if payload.clinic_name or role == SELF_SIGNUP_ROLE:
        clinic_name = payload.clinic_name or f"{payload.name}'s Business"
        did_val = payload.did.strip() if payload.did else None
        # Seed the agent with a vertical-specific starter prompt/greeting from
        # the chosen industry template (falls back to the generic defaults when
        # no/unknown industry is given). The client can edit these in Settings.
        tmpl = get_template(payload.industry)
        tenant = Tenant(
            name=clinic_name,
            subscription="free",
            did=did_val or None,
            industry=(payload.industry.strip().lower() if tmpl else None),
            system_prompt=(tmpl["system_prompt"] if tmpl else None),
            initial_greeting=(tmpl["initial_greeting"] if tmpl else None),
        )
        db.add(tenant)
        try:
            await db.flush()  # assigns tenant.id
        except IntegrityError:
            await db.rollback()
            return api_response(
                success=False,
                message="That clinic phone number (DID) is already registered",
                status_code=400,
            )
        clinic_id = tenant.id
        if did_val:
            logger.info(f"Registered clinic {clinic_name} with DID {did_val}")
            pn = PhoneNumber(clinic_id=clinic_id, number=did_val, label="Primary DID", status="active")
            db.add(pn)

    # Create the user
    user = User(
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        name=payload.name,
        role=role,
        clinic_id=clinic_id,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return api_response(success=False, message="Email already registered", status_code=400)

    user_id = str(user.id)
    clinic_id_str = str(clinic_id) if clinic_id else None

    access_token = create_access_token(session_claims(user, clinic_id_str))

    response_data = {
        "access_token": access_token,
        "token_type": "bearer",
        "id": user_id,
        "email": payload.email,
        "role": role,
        "name": payload.name,
        "clinic_id": clinic_id_str,
        "is_superadmin": is_superadmin(payload.email),
        # Always False right after signup — the confirmation email has only just
        # been sent. The dashboard uses this to show a "confirm your email" prompt.
        "email_verified": False,
    }
    await audit.record(
        audit.AUTH_REGISTER, actor_email=payload.email, clinic_id=clinic_id,
        target_type="user", target_id=user_id,
        detail={"role": role, "clinic_created": bool(clinic_id)},
        request=request,
    )
    # Send the verification link. Login is deliberately NOT blocked on it: with SMTP
    # unconfigured nobody could ever get in, and locking users out of a product they
    # just signed up for is worse than an unverified address. Verification does gate
    # platform admin (see require_superadmin), and the dashboard can nudge using the
    # `email_verified` flag in this response.
    await _send_verification_email(db, user)
    return api_response(success=True, message="Registration successful", data=response_data)


async def _send_verification_email(db: AsyncSession, user) -> None:
    """Issue a single-use verification token and email the link. Best-effort."""
    try:
        # Invalidate any earlier unused verification token so only the newest link
        # works — otherwise an old email remains a valid way in.
        previous = (await db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.purpose == "verify",
                PasswordResetToken.used_at.is_(None),
            )
        )).scalars().all()
        for row in previous:
            row.used_at = datetime.utcnow()

        raw = generate_token()
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            purpose="verify",
            expires_at=datetime.utcnow() + timedelta(hours=24),
        ))
        await db.commit()
        link = f"{settings.APP_BASE_URL}/verify-email?token={raw}"
        await asyncio.to_thread(
            send_email,
            user.email,
            "Confirm your Clarivo email address",
            f"Confirm your email address to finish setting up Clarivo (link valid for 24 hours):\n\n{link}\n\n"
            "If you didn't create this account, you can ignore this email.",
        )
    except Exception as e:  # noqa: BLE001 — must never fail the signup itself
        logger.error(f"Could not send verification email to {user.email}: {e}")


class GoogleSignIn(BaseModel):
    # The Supabase access token the browser receives after completing Google
    # sign-in. Verified server-side; nothing in it is trusted before that.
    access_token: str = Field(..., max_length=4096)
    # Optional, and only used when this sign-in creates a brand new account.
    clinic_name: Optional[str] = Field(default=None, max_length=255)
    industry: Optional[str] = Field(default=None, max_length=50)


@router.post("/oauth/google")
@limiter.limit("10/minute")
async def google_sign_in(
    request: Request,
    payload: GoogleSignIn,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a verified Google identity for one of THIS app's session tokens.

    Supabase Auth is used only to establish who the person is. It does not become
    the session: the response is the same token the password login returns, so every
    existing control keeps working unchanged — `clinic_id` tenant scoping, roles,
    `token_version` revocation, `is_active` suspension, and the audit trail.

    Three cases:
      * known account with this Google identity  -> sign in, refresh the profile
      * known account with the same EMAIL        -> link the Google identity to it
      * unknown email                            -> create the account and its tenant

    Linking on a matching email is safe here because `verify_google_token` has
    already required that Google confirmed the address. Without that requirement this
    would be an account-takeover path.
    """
    if not settings.google_oauth_enabled:
        return api_response(
            success=False,
            message="Google sign-in is not enabled on this server.",
            status_code=503,
        )

    try:
        identity = await verify_google_token(payload.access_token)
    except SupabaseAuthError as e:
        await audit.record(
            "auth.google_signin_failed", outcome="failure",
            detail={"reason": str(e)}, request=request,
        )
        return api_response(success=False, message=str(e), status_code=401)

    # Match on the provider id first: it is stable even if the person changes their
    # Google email address.
    user = (await db.execute(
        select(User).where(User.supabase_user_id == identity.supabase_user_id)
    )).scalar_one_or_none()
    linked_existing = False

    if user is None:
        user = (await db.execute(
            select(User).where(User.email == identity.email)
        )).scalar_one_or_none()
        if user is not None:
            # Same person, signing in a new way. Attach the identity rather than
            # creating a second account for the same address.
            user.supabase_user_id = identity.supabase_user_id
            linked_existing = True

    created = False
    if user is None:
        # New account. Mirrors /register: a tenant is created so the person lands in
        # their own workspace, seeded from the industry template.
        created = True
        clinic_name = (payload.clinic_name or "").strip() or (
            f"{identity.full_name or identity.email.split('@')[0]}'s Business"
        )
        tmpl = get_template(payload.industry)
        tenant = Tenant(
            name=clinic_name,
            subscription="free",
            industry=(payload.industry.strip().lower() if tmpl else None),
            system_prompt=(tmpl["system_prompt"] if tmpl else None),
            initial_greeting=(tmpl["initial_greeting"] if tmpl else None),
        )
        db.add(tenant)
        await db.flush()

        user = User(
            email=identity.email,
            # No password at all — see the note on the column. The account can only
            # be signed into with Google until the person sets one.
            password_hash=None,
            name=identity.full_name or identity.email.split("@")[0],
            # Same role every public sign-up gets. Never taken from the request.
            role=SELF_SIGNUP_ROLE,
            clinic_id=tenant.id,
            supabase_user_id=identity.supabase_user_id,
            # Set EXPLICITLY, not left to the column default. A model default is
            # applied when the row is INSERTed, so on a freshly constructed object
            # these are still None — and the suspension check below then read
            # `is_active = None` as "suspended" and refused every brand new account.
            is_active=True,
            token_version=0,
            failed_login_attempts=0,
        )
        db.add(user)
        # Assigns the id and applies any remaining defaults before the checks below.
        await db.flush()

    # Only an explicit False means suspended. `is not False` rather than a falsy
    # test on purpose: None here means "not yet persisted", not "disabled".
    if getattr(user, "is_active", True) is False:
        # A suspended account must not be able to walk back in through a second door.
        await audit.record(
            "auth.google_signin_failed", actor_email=user.email,
            clinic_id=user.clinic_id, outcome="failure",
            detail={"reason": "account_suspended"}, request=request,
        )
        return api_response(
            success=False,
            message="This account has been suspended. Please contact support.",
            status_code=403,
        )

    # Profile sync, on every sign-in: name and avatar can change on Google's side.
    # An existing name is not overwritten with a blank one.
    if identity.full_name:
        user.name = identity.full_name
    if identity.avatar_url:
        user.avatar_url = identity.avatar_url
    # Google has already confirmed the address, so asking for our own proof would be
    # asking for something we already have.
    if user.email_verified_at is None:
        user.email_verified_at = datetime.utcnow()
    user.updated_at = datetime.utcnow()
    # Clears any brute-force lockout: proving control of the Google account is
    # stronger evidence than the lockout is protection.
    login_guard.register_success(user)

    await db.commit()
    await db.refresh(user)

    clinic_id_str = str(user.clinic_id) if user.clinic_id else None
    access_token = create_access_token(session_claims(user, clinic_id_str))

    await audit.record(
        audit.AUTH_LOGIN, actor_email=user.email, clinic_id=user.clinic_id,
        target_type="user", target_id=user.id,
        detail={"provider": "google", "account_created": created,
                "identity_linked": linked_existing},
        request=request,
    )

    return api_response(
        success=True,
        message="Signed in with Google",
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "id": str(user.id),
            "email": user.email,
            "role": user.role,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "clinic_id": clinic_id_str,
            "is_superadmin": is_superadmin(user.email),
            "email_verified": user.email_verified_at is not None,
            # Lets the dashboard send a first-time user through onboarding.
            "is_new_account": created,
        },
    )


class VerifyEmail(BaseModel):
    token: str = Field(..., max_length=256)


@router.post("/verify-email")
@limiter.limit("10/minute")
async def verify_email(request: Request, payload: VerifyEmail, db: AsyncSession = Depends(get_db)):
    """Confirm ownership of an email address using the emailed token."""
    row = (await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(payload.token),
            PasswordResetToken.purpose == "verify",
        )
    )).scalar_one_or_none()
    if not row or row.used_at is not None or row.expires_at < datetime.utcnow():
        return api_response(
            success=False,
            message="That confirmation link is invalid or has expired. Request a new one.",
            status_code=400,
        )

    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if not user:
        return api_response(success=False, message="Account not found", status_code=404)

    if user.email_verified_at is None:
        user.email_verified_at = datetime.utcnow()
    row.used_at = datetime.utcnow()
    await db.commit()

    await audit.record(
        "auth.email_verified", actor_email=user.email, clinic_id=user.clinic_id,
        target_type="user", target_id=user.id, request=request,
    )
    return api_response(success=True, message="Email address confirmed.")


@router.post("/resend-verification")
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a fresh verification link to the signed-in user's address.

    Requires a session, so it cannot be used to spam an arbitrary mailbox. Rate
    limited more tightly than the rest for the same reason.
    """
    user = (await db.execute(
        select(User).where(User.id == to_uuid(current_user["id"]))
    )).scalar_one_or_none()
    if not user:
        return api_response(success=False, message="Account not found", status_code=404)
    if user.email_verified_at is not None:
        return api_response(success=True, message="Your email address is already confirmed.")

    await _send_verification_email(db, user)
    return api_response(
        success=True,
        message="Confirmation email sent. Check your inbox.",
    )


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, payload: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # Identical wording for every rejection below. Anything more specific turns
    # this endpoint into an oracle for which addresses are registered.
    invalid = api_response(success=False, message="Invalid email or password", status_code=400)

    if not user:
        # Spend a comparable amount of time on a non-existent account so response
        # timing does not reveal whether the address is registered.
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        await audit.record(
            audit.AUTH_LOGIN_FAILED, actor_email=payload.email, outcome="failure",
            detail={"reason": "unknown_email"}, request=request,
        )
        return invalid

    if not user.password_hash:
        # Created through Google, so there is no password to check. Still spend the
        # bcrypt time, otherwise a fast rejection here reveals which accounts are
        # Google-only. The message names Google because a generic "invalid password"
        # would leave the person retrying a password they never set.
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        await audit.record(
            audit.AUTH_LOGIN_FAILED, actor_email=user.email, clinic_id=user.clinic_id,
            outcome="failure", detail={"reason": "password_login_on_google_account"},
            request=request,
        )
        return api_response(
            success=False,
            message=(
                "This account uses Google sign-in. Use \"Continue with Google\", or "
                "set a password first with \"Forgot password\"."
            ),
            status_code=400,
        )

    # Verify the password even when the account is locked, so a locked account and
    # a wrong password cost about the same. Returning early here would leak lock
    # state through response timing.
    password_ok = verify_password(payload.password, user.password_hash)

    if login_guard.is_locked(user):
        mins = login_guard.lock_remaining_minutes(user)
        logger.warning(f"Rejected login for locked account {user.email} ({mins}m remaining).")
        await audit.record(
            audit.AUTH_LOGIN_FAILED, actor_email=user.email, clinic_id=user.clinic_id,
            outcome="failure", detail={"reason": "account_locked", "minutes_remaining": mins},
            request=request,
        )
        return api_response(
            success=False,
            message=(
                "Too many failed sign-in attempts. This account is temporarily "
                f"locked — try again in about {mins} minute(s), or reset your password."
            ),
            status_code=429,
        )

    if not password_ok:
        # Per-ACCOUNT lockout. The IP rate limit above is flood protection only; it
        # does nothing against credential stuffing from a pool of addresses.
        locked = login_guard.register_failure(user)
        await db.commit()
        await audit.record(
            audit.AUTH_LOCKED if locked else audit.AUTH_LOGIN_FAILED,
            actor_email=user.email, clinic_id=user.clinic_id, outcome="failure",
            detail={"reason": "wrong_password",
                    "failed_attempts": int(user.failed_login_attempts or 0)},
            request=request,
        )
        if locked:
            return api_response(
                success=False,
                message=(
                    "Too many failed sign-in attempts. This account has been "
                    f"temporarily locked for {login_guard.lock_remaining_minutes(user)} "
                    "minute(s). You can reset your password to regain access sooner."
                ),
                status_code=429,
            )
        return invalid

    if not bool(getattr(user, "is_active", True)):
        # Same generic wording as a bad password: whether an account exists and
        # whether it is suspended are both details worth not confirming.
        return invalid

    # Genuine sign-in: clear the failure counter and stamp the login time.
    login_guard.register_success(user)
    await db.commit()
    await audit.record(
        audit.AUTH_LOGIN, actor_email=user.email, clinic_id=user.clinic_id,
        target_type="user", target_id=user.id, request=request,
    )

    clinic_id_str = str(user.clinic_id) if user.clinic_id else None
    access_token = create_access_token(session_claims(user, clinic_id_str))

    response_data = {
        "access_token": access_token,
        "token_type": "bearer",
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "name": user.name,
        "clinic_id": clinic_id_str,
        "is_superadmin": is_superadmin(user.email),
        "email_verified": user.email_verified_at is not None,
    }
    return api_response(success=True, message="Login successful", data=response_data)


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    user_response = {
        "id": current_user["id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "role": current_user["role"],
        "clinic_id": current_user.get("clinic_id"),
        "is_superadmin": is_superadmin(current_user["email"]),
        # Lets the dashboard prompt for confirmation. Login is not blocked on it,
        # but platform admin is (see require_superadmin).
        "email_verified": current_user.get("email_verified_at") is not None,
    }
    return api_response(success=True, message="Current user fetched successfully", data=user_response)


class ChangePassword(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return validate_password_strength(v)


class ProfileUpdate(BaseModel):
    name: str = Field(..., min_length=1)


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str = Field(..., max_length=256)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return validate_password_strength(v)


@router.put("/profile")
async def update_profile(
    payload: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.id == to_uuid(current_user["id"])))).scalar_one_or_none()
    if not user:
        return api_response(success=False, message="User not found", status_code=404)
    user.name = payload.name.strip()
    await db.commit()
    return api_response(success=True, message="Profile updated", data={"name": user.name})


@router.post("/change-password")
async def change_password(
    payload: ChangePassword,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.id == to_uuid(current_user["id"])))).scalar_one_or_none()
    if not user:
        return api_response(success=False, message="User not found", status_code=404)
    if not verify_password(payload.current_password, user.password_hash):
        return api_response(success=False, message="Current password is incorrect", status_code=400)
    user.password_hash = get_password_hash(payload.new_password)
    # Changing a password must end every OTHER session — that is the whole point
    # when someone changes it because they think an account is compromised.
    # Bumping the version invalidates this browser's token too, so we hand back a
    # freshly minted one and the user stays signed in here.
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
    user.password_changed_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)
    await audit.record(
        audit.AUTH_PASSWORD_CHANGED, actor=current_user,
        target_type="user", target_id=user.id,
        detail={"other_sessions_revoked": True},
    )
    return api_response(
        success=True,
        message="Password changed. You have been signed out on all other devices.",
        data={"access_token": create_access_token(session_claims(user)), "token_type": "bearer"},
    )


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, payload: ForgotPassword, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user:
        raw = generate_token()
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            purpose="reset",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ))
        await db.commit()
        link = f"{settings.APP_BASE_URL}/reset-password?token={raw}"
        await asyncio.to_thread(
            send_email,
            user.email,
            "Reset your Clarivo password",
            f"Use this link to reset your password (valid for 1 hour):\n\n{link}\n\n"
            "If you didn't request this, you can safely ignore this email.",
        )
    # Anti-enumeration: identical response whether or not the email exists.
    return api_response(success=True, message="If that email is registered, a reset link has been sent.")


@router.post("/reset-password")
@limiter.limit("10/minute")
async def reset_password(request: Request, payload: ResetPassword, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(payload.token)
    row = (await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )).scalar_one_or_none()
    if not row or row.used_at is not None or row.expires_at < datetime.utcnow():
        return api_response(success=False, message="This link is invalid or has expired.", status_code=400)
    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if not user:
        return api_response(success=False, message="This link is invalid or has expired.", status_code=400)
    user.password_hash = get_password_hash(payload.new_password)
    # A reset is the recovery path for a compromised account, so every existing
    # session must die — otherwise an attacker holding a stolen token keeps access
    # even after the legitimate owner resets the password.
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
    user.password_changed_at = datetime.utcnow()
    # Clear any brute-force lockout. Proving control of the mailbox is stronger
    # evidence than the lockout is protection, and the lockout message tells users
    # to reset their password to get back in — so it has to actually work.
    user.failed_login_attempts = 0
    user.locked_until = None
    row.used_at = datetime.utcnow()

    # Burn any other unused reset tokens for this user, so an older emailed link
    # cannot be replayed to take the account over again.
    others = (await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )).scalars().all()
    for t in others:
        t.used_at = datetime.utcnow()

    await db.commit()
    await audit.record(
        audit.AUTH_PASSWORD_RESET, actor_email=user.email, clinic_id=user.clinic_id,
        target_type="user", target_id=user.id,
        detail={"all_sessions_revoked": True, "lockout_cleared": True},
        request=request,
    )
    return api_response(success=True, message="Password set successfully. You can now sign in.")


@router.post("/logout-all-devices")
async def logout_all_devices(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End every session for this account, including this one.

    Real server-side logout. Previously "logout" only cleared localStorage, so a
    token copied off the machine stayed valid for its full 7-day lifetime with no
    way to stop it.
    """
    user = (await db.execute(
        select(User).where(User.id == to_uuid(current_user["id"]))
    )).scalar_one_or_none()
    if not user:
        return api_response(success=False, message="User not found", status_code=404)
    user.token_version = int(getattr(user, "token_version", 0) or 0) + 1
    await db.commit()
    logger.info(f"User {user.email} revoked all sessions.")
    await audit.record(
        audit.AUTH_LOGOUT_ALL, actor=current_user, target_type="user", target_id=user.id,
    )
    return api_response(
        success=True,
        message="Signed out on all devices. Please sign in again.",
    )


class StaffCreate(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    # Was min_length=6, which bypassed the policy every other password path
    # enforces (10 characters, three character classes, common-password blocklist).
    # A staff account is a real login into a tenant's patient data, so it cannot be
    # the one place where "123456" is acceptable.
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=128)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        return validate_password_strength(v)


@router.post("/staff")
@limiter.limit("10/minute")
async def create_staff(
    request: Request,
    payload: StaffCreate,
    current_user: dict = Depends(require_roles(["doctor"])),
    db: AsyncSession = Depends(get_db),
):
    """Create a staff account scoped to the calling doctor's clinic.

    Only users with role "doctor" may call this endpoint. The created user
    inherits the same clinic_id and is assigned role "staff", which grants
    read-only access to patient data and hides billing/setup nav items.

    Notes on the guarantees here:
      * `role` is hardcoded, so this cannot be used to mint an admin.
      * `clinic_id` comes from the CALLER, never the payload, so a doctor can only
        create staff inside their own tenant.
      * The account starts unverified. That is deliberate: the owner creating it is
        vouching for the address, and blocking sign-in on verification would leave
        new staff unable to work while SMTP is unconfigured.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with your account", status_code=400)

    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing:
        return api_response(success=False, message="Email already registered", status_code=400)

    staff = User(
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        name=payload.name.strip(),
        role="staff",
        clinic_id=clinic_id,
    )
    db.add(staff)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return api_response(success=False, message="Email already registered", status_code=400)

    # Creating a login into a tenant's patient data is security-relevant, so it must
    # be attributable — who created this account, when, and from where.
    await audit.record(
        "auth.staff_created", actor=current_user, clinic_id=clinic_id,
        target_type="user", target_id=staff.id,
        detail={"staff_email": staff.email, "role": staff.role},
        request=request,
    )

    return api_response(
        success=True,
        message=f"Staff account created for {staff.name}",
        data={
            "id": str(staff.id),
            "email": staff.email,
            "name": staff.name,
            "role": staff.role,
            "clinic_id": str(clinic_id),
        },
    )


class StaffAccess(BaseModel):
    # True = can sign in, False = suspended. Suspending also revokes live sessions.
    active: bool


async def _staff_member_or_error(staff_id: str, current_user: dict, db: AsyncSession):
    """Resolve a staff row the caller is actually allowed to manage.

    Three conditions, and all three matter:
      * the id parses — otherwise a garbage path segment reaches the query
      * the row is in the CALLER's clinic — the clinic comes from the token, never
        the request, so a doctor cannot reach into another tenant
      * the row's role is exactly "staff" — this is what stops a doctor deleting a
        fellow doctor, the clinic owner, or their own account through this endpoint

    Returns (user, None) or (None, error_response). Deliberately returns the same
    404 for "no such id", "other tenant" and "not a staff account", so the endpoint
    cannot be used to probe which user ids or roles exist.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    sid = to_uuid(staff_id)
    if clinic_id is None or sid is None:
        return None, api_response(success=False, message="Staff account not found", status_code=404)

    member = (await db.execute(
        select(User).where(User.id == sid, User.clinic_id == clinic_id)
    )).scalar_one_or_none()

    if member is None or member.role != "staff":
        return None, api_response(success=False, message="Staff account not found", status_code=404)

    return member, None


@router.get("/staff")
async def list_staff(
    current_user: dict = Depends(require_roles(["doctor"])),
    db: AsyncSession = Depends(get_db),
):
    """Staff accounts belonging to the calling doctor's clinic.

    Scoped by the caller's own clinic_id, so this cannot enumerate another tenant's
    team. No password material is returned — only what the management screen shows.
    """
    clinic_id = to_uuid(current_user.get("clinic_id"))
    if clinic_id is None:
        return api_response(success=False, message="No clinic associated with your account", status_code=400)

    members = (await db.execute(
        select(User)
        .where(User.clinic_id == clinic_id, User.role == "staff")
        .order_by(User.created_at.desc())
    )).scalars().all()

    return api_response(
        success=True,
        message="Staff fetched successfully",
        data=[
            {
                "id": str(m.id),
                "name": m.name,
                "email": m.email,
                "is_active": bool(m.is_active),
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "last_login_at": m.last_login_at.isoformat() if m.last_login_at else None,
                "email_verified": m.email_verified_at is not None,
            }
            for m in members
        ],
    )


@router.patch("/staff/{staff_id}")
@limiter.limit("20/minute")
async def set_staff_access(
    staff_id: str,
    payload: StaffAccess,
    request: Request,
    current_user: dict = Depends(require_roles(["doctor"])),
    db: AsyncSession = Depends(get_db),
):
    """Suspend or restore a staff account.

    Preferred over deletion for someone who has simply left or is away: it stops
    sign-in immediately while keeping their record and their attribution on the
    contacts they added.

    Suspending bumps `token_version`, which invalidates every token already issued
    to them. Without that they would keep working until their current token expired
    — up to a full day — which is not what "suspend" means to the person clicking it.
    """
    member, error = await _staff_member_or_error(staff_id, current_user, db)
    if error:
        return error

    member.is_active = payload.active
    if not payload.active:
        member.token_version = int(member.token_version or 0) + 1
    await db.commit()

    await audit.record(
        "auth.staff_access_changed", actor=current_user, clinic_id=member.clinic_id,
        target_type="user", target_id=member.id,
        detail={"staff_email": member.email, "active": bool(payload.active)},
        request=request,
    )

    return api_response(
        success=True,
        message=f"{member.name} can sign in again" if payload.active else f"{member.name} is suspended",
        data={"id": str(member.id), "is_active": bool(member.is_active)},
    )


@router.delete("/staff/{staff_id}")
@limiter.limit("10/minute")
async def delete_staff(
    staff_id: str,
    request: Request,
    current_user: dict = Depends(require_roles(["doctor"])),
    db: AsyncSession = Depends(get_db),
):
    """Permanently remove a staff account.

    Safe to hard-delete: every foreign key pointing at `users.id` from our own
    tables is ON DELETE SET NULL (`patients.created_by`, `audit_logs.actor_user_id`)
    or CASCADE (`password_reset_tokens`), verified against the live database — so
    contacts they added survive with `created_by` cleared rather than being dragged
    down with them.

    Their audit history also survives, because `audit_logs.actor_email` is stored as
    text alongside the id. Losing the id does not lose who did what.

    Any token they still hold stops working immediately: `get_current_user` looks the
    row up on every request and a missing row is a 401.
    """
    member, error = await _staff_member_or_error(staff_id, current_user, db)
    if error:
        return error

    removed = {"staff_email": member.email, "staff_name": member.name}

    await db.delete(member)
    await db.commit()

    await audit.record(
        "auth.staff_deleted", actor=current_user, clinic_id=to_uuid(current_user.get("clinic_id")),
        target_type="user", target_id=staff_id, detail=removed, request=request,
    )

    return api_response(success=True, message=f"Removed {removed['staff_name']}")
