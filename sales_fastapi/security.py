"""Authentication & secret handling.

- Google Sign-In: verify the Google Identity Services ID token, then issue our
  own short-lived JWT session token.
- Passwords for IMAP/SMTP are encrypted at rest with Fernet (key derived from
  SECRET_KEY) and never returned through the API.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User


# --------------------------------------------------------------------------
# Password / secret encryption
# --------------------------------------------------------------------------
def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:  # pragma: no cover - optional dependency
        return None
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    f = _fernet()
    if f is None:
        return "b64:" + base64.b64encode(plain.encode()).decode()
    return "fernet:" + f.encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    if token.startswith("b64:"):
        return base64.b64decode(token[4:]).decode()
    if token.startswith("fernet:"):
        f = _fernet()
        if f is None:
            return ""
        return f.decrypt(token[7:].encode()).decode()
    return ""


# --------------------------------------------------------------------------
# JWT session tokens
# --------------------------------------------------------------------------
def create_access_token(user: User) -> tuple[str, int]:
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, int(expires.total_seconds())


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# --------------------------------------------------------------------------
# Google ID token verification
# --------------------------------------------------------------------------
def verify_google_id_token(token: str) -> dict:
    """Return the Google profile claims for a valid ID token.

    In AUTH_DEV_MODE, a synthetic token of the form ``dev:<email>`` is accepted
    so the app can be exercised locally without a Google client.
    """
    if settings.AUTH_DEV_MODE and token.startswith("dev:"):
        email = token[4:].strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="dev token needs an email")
        return {
            "sub": f"dev-{email}",
            "email": email,
            "name": email.split("@")[0].title(),
            "picture": "",
            "email_verified": True,
        }

    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="GOOGLE_CLIENT_ID is not configured on the server",
        )

    try:
        claims = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {exc}") from exc

    if not claims.get("email_verified", False):
        raise HTTPException(status_code=403, detail="Google email is not verified")

    allowed = [d.strip().lower() for d in settings.GOOGLE_ALLOWED_DOMAINS.split(",") if d.strip()]
    if allowed:
        email_domain = claims.get("email", "").split("@")[-1].lower()
        if email_domain not in allowed:
            raise HTTPException(status_code=403, detail="Email domain not allowed")
    return claims


# --------------------------------------------------------------------------
# FastAPI dependencies
# --------------------------------------------------------------------------
def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    claims = decode_access_token(authorization.split(" ", 1)[1])
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user
