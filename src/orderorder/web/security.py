"""Cryptographic authentication and session security.

Uses standard-library hashlib.scrypt with cryptographically random salts, constant-time digest
comparisons, and opaque high-entropy session tokens stored with explicit expiration.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from orderorder.db.models import User, UserSession

SESSION_COOKIE_NAME = "orderorder_session"
SESSION_DURATION_DAYS = 7

# Scrypt parameters recommended by OWASP: N=16384 (2^14), r=8, p=1
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if len(password) > 128:
        return "Password must not exceed 128 characters."
    return None


def hash_password(password: str) -> str:
    """Hash password using scrypt with a 16-byte cryptographic random salt."""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against scrypt hash in constant time."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        _, n_str, r_str, p_str, salt_hex, expected_hex = parts
        n, r, p = int(n_str), int(r_str), int(p_str)
        salt = bytes.fromhex(salt_hex)
        expected_dk = bytes.fromhex(expected_hex)

        actual_dk = hashlib.scrypt(
            plain_password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected_dk),
        )
        return hmac.compare_digest(actual_dk, expected_dk)
    except Exception:
        return False


def create_user_session(
    db: Session,
    user_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    duration_days: int = SESSION_DURATION_DAYS,
) -> UserSession:
    """Generate a high-entropy session token and persist to database."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(days=duration_days)

    session_obj = UserSession(
        user_id=user_id,
        session_token=token,
        ip_address=ip_address[:45] if ip_address else None,
        user_agent=user_agent[:255] if user_agent else None,
        expires_at=expires,
        created_at=now,
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)
    return session_obj


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def get_user_by_session_token(db: Session, token: str) -> User | None:
    """Retrieve active user for a valid, non-expired session token."""
    if not token or len(token) < 20:
        return None

    now = datetime.now(UTC)
    session_obj = db.scalars(
        select(UserSession).where(UserSession.session_token == token)
    ).first()

    if not session_obj:
        return None

    # Handle expired session cleanly (timezone-safe comparison)
    if _as_utc(session_obj.expires_at) <= now:
        db.execute(delete(UserSession).where(UserSession.id == session_obj.id))
        db.commit()
        return None

    user = db.get(User, session_obj.user_id)
    if not user or not user.is_active:
        return None

    return user


def revoke_session(db: Session, token: str) -> None:
    """Invalidate a session token."""
    if not token:
        return
    db.execute(delete(UserSession).where(UserSession.session_token == token))
    db.commit()


def get_current_user(request: Request, db: Session) -> User | None:
    """Extract authenticated user from session cookie or Authorization Bearer header."""
    # 1. Cookie check
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        user = get_user_by_session_token(db, token)
        if user:
            return user

    # 2. Authorization header check (fallback for API / tests)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:].strip()
        return get_user_by_session_token(db, bearer_token)

    return None
