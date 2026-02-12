"""
Authentication helpers for the Generator Booking Ledger.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any

import jwt

from passlib.context import CryptContext

from .repositories import UserRepository
from config import ROLE_ADMIN

logger = logging.getLogger(__name__)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_BCRYPT_MAX_BYTES = 72


def _password_bytes_len(password: str) -> int:
    return len(password.encode("utf-8"))


def validate_password_length(password: str) -> None:
    """Raise if password exceeds bcrypt's 72-byte limit."""
    if _password_bytes_len(password) > _BCRYPT_MAX_BYTES:
        raise ValueError(
            "Password too long for bcrypt (max 72 bytes). "
            "Use a shorter password."
        )


def hash_password(password: str) -> str:
    """Hash a plain-text password."""
    validate_password_length(password)
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored hash."""
    if _password_bytes_len(password) > _BCRYPT_MAX_BYTES:
        return False
    return _pwd_context.verify(password, password_hash)


def ensure_owner_user(
    conn,
    username: str,
    password: str,
    strict: bool = True
) -> bool:
    """
    Ensure at least one admin user exists. If none exist, create one.
    Returns True if a new owner was created.
    """
    repo = UserRepository(conn)
    if repo.count_users() > 0:
        return False

    if not username or not password:
        msg = "OWNER_USERNAME and OWNER_PASSWORD are required to bootstrap the first admin user."
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)
        return False

    validate_password_length(password)
    password_hash = hash_password(password)
    repo.create_user(username, password_hash, role=ROLE_ADMIN, is_active=True)
    logger.info("Created initial owner admin user | context={'username': '%s'}", username)
    return True


def generate_session_id() -> str:
    """Generate a random session identifier."""
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    """Generate a random CSRF token."""
    return secrets.token_urlsafe(32)


def create_access_token(
    user_id: int,
    username: str,
    role: str,
    secret: str,
    algorithm: str,
    expires_minutes: int,
) -> Tuple[str, int, str]:
    """Create a signed JWT access token with expiry."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes)
    jti = secrets.token_urlsafe(16)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, int(exp.timestamp()), jti


def decode_access_token(
    token: str,
    secret: str,
    algorithm: str,
    verify_exp: bool = True,
) -> Dict[str, Any]:
    """Decode and validate a JWT access token."""
    options = {"verify_exp": verify_exp}
    return jwt.decode(token, secret, algorithms=[algorithm], options=options)
