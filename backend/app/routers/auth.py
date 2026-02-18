"""
AUTH ROUTER
-----------
Handles:
- Login (issue access + refresh tokens)
- Refresh (rotate refresh token)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from app.services.firebase_service import db
from app.services.auth_service import (
    verify_password,
    create_access_token,
    create_refresh_token,
    rotate_refresh_token
)
from fastapi import Depends
from app.utils.rbac import get_current_user

router = APIRouter()


# -----------------------------
# REQUEST MODELS
# -----------------------------

class LoginRequest(BaseModel):
    email: str
    password: str
    device: str = "Browser"


class RefreshRequest(BaseModel):
    refresh_token: str
    device: str = "Browser"


# -----------------------------
# LOGIN ENDPOINT
# -----------------------------

@router.post("/login")
def login(data: LoginRequest):
    """
    1. Find user by email
    2. Verify password
    3. Issue access + refresh tokens
    """

    # 🔥 Search by EMAIL (NOT username)
    query = db.collection("users") \
              .where("email", "==", data.email) \
              .limit(1) \
              .stream()

    doc = next(query, None)

    if not doc:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id = doc.id
    user = doc.to_dict()

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="User disabled")

    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Update last login timestamp
    db.collection("users").document(user_id).set({
        "last_login_at": datetime.utcnow()
    }, merge=True)

    access_token = create_access_token(
        user_id=user_id,
        role=user["role"]
    )

    refresh_token = create_refresh_token(
        user_id=user_id,
        device=data.device
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


# -----------------------------
# REFRESH ENDPOINT
# -----------------------------

@router.post("/refresh")
def refresh(data: RefreshRequest):
    try:
        new_access, new_refresh = rotate_refresh_token(
            old_refresh_token=data.refresh_token,
            device=data.device
        )

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "bearer"
        }

    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"status": "success", "data": user}