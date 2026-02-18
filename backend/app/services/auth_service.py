"""
AUTH SERVICE
------------
Security engine for authentication & token lifecycle.

Responsibilities:
- Hash and verify passwords (bcrypt)
- Generate access tokens (JWT, short-lived)
- Generate refresh tokens (long-lived, stored hashed in Firestore)
- Decode and validate access tokens
- Rotate refresh tokens (revoke old, issue new)

Why timezone-aware UTC?
- Prevents immediate-expiry issues due to naive datetime -> timestamp conversion
- Avoids local timezone offset bugs (common on Windows)
"""

import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from dotenv import load_dotenv
from app.services.firebase_service import db

# Load environment variables from .env
load_dotenv()

# Password hashing engine (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Load security configs from .env
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))

# Fail fast if secret is not configured (enterprise hygiene)
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is missing. Set it in your .env file.")


# -----------------------------
# PASSWORD HANDLING
# -----------------------------

def hash_password(password: str) -> str:
    """
    Hashes a plaintext password before storing in Firestore.
    """
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verifies a plaintext password against its bcrypt hash.
    """
    return pwd_context.verify(password, password_hash)


# -----------------------------
# ACCESS TOKEN (JWT)
# -----------------------------

def create_access_token(user_id: str, role: str) -> str:
    """
    Creates a short-lived JWT access token.

    Payload fields (standard practice):
    - sub: subject (user id)
    - role: RBAC role (admin/user)
    - iat: issued-at (epoch seconds)
    - exp: expiry (epoch seconds)
    """
    now = datetime.now(timezone.utc)  # timezone-aware UTC
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_MINUTES)).timestamp()),
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Validates JWT signature + expiry.
    Returns decoded payload if valid.
    Raises ValueError if invalid/expired (caller converts to HTTP 401).
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        # Do not leak internal JWT errors to clients in production
        raise ValueError("Invalid or expired access token")


# -----------------------------
# REFRESH TOKEN HANDLING
# -----------------------------

def _hash_refresh_token(token: str) -> str:
    """
    Hash refresh tokens before storing in DB.
    We never store raw refresh tokens server-side.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_token(user_id: str, device: str = "unknown") -> str:
    """
    Generates a secure refresh token and stores its hash in Firestore.

    Returns:
    - raw refresh token (send to client)
    """
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_refresh_token(raw_token)

    now = datetime.now(timezone.utc)  # timezone-aware UTC
    expires_at = now + timedelta(days=REFRESH_TOKEN_DAYS)

    db.collection("refresh_tokens").add({
        "user_id": user_id,
        "token_hash": token_hash,
        "created_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
        "device": device,
    })

    return raw_token


def rotate_refresh_token(old_refresh_token: str, device: str = "unknown"):
    """
    Refresh token rotation (best practice):
    - Validate old refresh token hash exists
    - Reject if revoked or expired
    - Revoke old token
    - Issue new access token + new refresh token

    Returns:
    - (new_access_token, new_refresh_token)
    """
    token_hash = _hash_refresh_token(old_refresh_token)

    query = (
        db.collection("refresh_tokens")
        .where("token_hash", "==", token_hash)
        .limit(1)
        .stream()
    )

    doc = next(query, None)
    if not doc:
        raise ValueError("Invalid refresh token")

    data = doc.to_dict()

    # Check revoked
    if data.get("revoked_at") is not None:
        raise ValueError("Refresh token already revoked")

    # Check expiry (timezone-aware UTC)
    now = datetime.now(timezone.utc)
    expires_at = data.get("expires_at")
    if expires_at is None:
        raise ValueError("Refresh token record corrupted (missing expires_at)")
    if now > expires_at:
        raise ValueError("Refresh token expired")

    user_id = data["user_id"]

    # Revoke old token (rotation)
    db.collection("refresh_tokens").document(doc.id).set({
        "revoked_at": now
    }, merge=True)

    # Load user to get role and validate active status
    user_doc = db.collection("users").document(user_id).get()
    if not user_doc.exists:
        raise ValueError("User not found")

    user = user_doc.to_dict()
    if not user.get("is_active", True):
        raise ValueError("User disabled")

    new_access = create_access_token(user_id=user_id, role=user["role"])
    new_refresh = create_refresh_token(user_id=user_id, device=device)

    return new_access, new_refresh
