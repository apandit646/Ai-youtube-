from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import AppSettings, User
from app.services.settings_service import get_app_settings

bearer = HTTPBearer(auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def get_current_user(db: DB, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    sub = decode_access_token(creds.credentials)
    user = db.get(User, int(sub)) if sub and sub.isdigit() else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_settings_for_user(db: DB, user: CurrentUser) -> AppSettings:
    return get_app_settings(db, user.id)


UserSettings = Annotated[AppSettings, Depends(get_settings_for_user)]


class Pagination:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


Paging = Annotated[Pagination, Depends()]


def owned(obj, user: User, name: str = "Resource"):
    """Authorization check: every protected resource must belong to the current user."""
    from app.core.errors import NotFoundError

    if obj is None or getattr(obj, "owner_id", None) != user.id:
        raise NotFoundError(f"{name} not found")
    return obj
