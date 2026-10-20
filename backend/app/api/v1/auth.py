from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.api import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.audit import audit
from app.services.settings_service import get_app_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/setup-status")
def setup_status(db: DB) -> dict:
    """Public: tells the UI whether the initial owner account still needs to be created."""
    users = db.scalar(select(func.count(User.id))) or 0
    return {"needs_owner": users == 0}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: DB) -> TokenResponse:
    # Single-owner MVP: registration is only open until the first account exists.
    if (db.scalar(select(func.count(User.id))) or 0) > 0:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed; an owner account already exists")
    user = User(email=body.email.lower(), hashed_password=hash_password(body.password),
                display_name=body.display_name or body.email.split("@")[0])
    db.add(user)
    db.flush()
    get_app_settings(db, user.id)
    audit(db, user.id, "auth.register", "user", user.id)
    db.commit()
    return _token(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: DB) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.hashed_password):
        audit(db, user.id if user else None, "auth.login_failed", "user", body.email.lower())
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    audit(db, user.id, "auth.login", "user", user.id)
    db.commit()
    return _token(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


def _token(user: User) -> TokenResponse:
    minutes = get_settings().access_token_expire_minutes
    return TokenResponse(access_token=create_access_token(str(user.id)), expires_in=minutes * 60)
