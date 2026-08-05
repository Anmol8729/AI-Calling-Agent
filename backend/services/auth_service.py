from datetime import datetime, timedelta
from typing import Optional, Union, Any
from jose import jwt, JWTError
import bcrypt
import secrets
import hashlib
from backend.config.settings import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Sign a user session token.

    Callers should include a `ver` claim carrying the user's `token_version`;
    `get_current_user` compares it against the database on every request, which is
    what allows a session to be revoked (password change, "log out everywhere",
    suspension). A token minted without `ver` is treated as version 0, so tokens
    issued before that column existed keep working instead of logging everyone out.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def session_claims(user, clinic_id_str: Optional[str] = None) -> dict:
    """Standard claim set for a user session token.

    One place to build these, so login, registration and any future path cannot
    drift apart and accidentally omit `ver` (which would make that token
    unrevocable).
    """
    return {
        "sub": str(user.id),
        "role": user.role,
        "clinic_id": clinic_id_str if clinic_id_str is not None else (
            str(user.clinic_id) if user.clinic_id else None
        ),
        "ver": int(getattr(user, "token_version", 0) or 0),
    }

def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def generate_token() -> str:
    """Return a URL-safe random token (the plaintext handed to the user)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex of a token; only this hash is ever stored at rest."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
