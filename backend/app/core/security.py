"""Password hashing and JWT helpers."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import Settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash in configuration.
        return False


ACCESS = "access"
PREMIUM_UNLOCK = "premium_unlock"


def _create_token(subject: str, token_type: str, seconds: int, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "iat": now, "exp": now + timedelta(seconds=seconds), "type": token_type}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_token(token: str, token_type: str, settings: Settings) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != token_type:
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def create_access_token(subject: str, settings: Settings) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    expires_in = settings.access_token_expire_minutes * 60
    return _create_token(subject, ACCESS, expires_in, settings), expires_in


def decode_access_token(token: str, settings: Settings) -> str | None:
    """Return the subject (user id) if the token is valid, otherwise None."""
    return _decode_token(token, ACCESS, settings)


def create_premium_unlock_token(subject: str, settings: Settings) -> tuple[str, int]:
    """Short-lived proof that the user re-entered their password (premium models)."""
    expires_in = settings.premium_unlock_minutes * 60
    return _create_token(subject, PREMIUM_UNLOCK, expires_in, settings), expires_in


def is_valid_premium_unlock(token: str | None, user_id: str, settings: Settings) -> bool:
    return bool(token) and _decode_token(token, PREMIUM_UNLOCK, settings) == user_id
