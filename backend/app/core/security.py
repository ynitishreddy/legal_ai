from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)


# Keep old name as alias so nothing breaks
get_password_hash = hash_password


def _build_payload(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    expire = datetime.now(timezone.utc) + expires_delta
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "type": token_type,
        "iat": datetime.now(timezone.utc),
    }
    if extra:
        payload.update(extra)
    return payload


def create_access_token(
    subject: str | int,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    """Create a signed JWT access token."""
    delta = expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    payload = _build_payload(str(subject), "access", delta, extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(subject: str | int) -> str:
    """Create a signed JWT refresh token."""
    delta = timedelta(days=settings.refresh_token_expire_days)
    payload = _build_payload(str(subject), "refresh", delta)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_token_pair(user_id: UUID | str, email: str, role: str) -> dict[str, Any]:
    """
    Build both access and refresh tokens with the full required payload:
        { sub, email, role, exp, type }
    Returns a dict matching TokenResponse fields.
    """
    claims = {"email": email, "role": role}
    access = create_access_token(subject=str(user_id), extra_claims=claims)
    refresh = create_refresh_token(subject=str(user_id))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and validate a JWT. Returns payload dict or None on failure."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
