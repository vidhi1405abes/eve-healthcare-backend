from dataclasses import dataclass

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import BEARER_HEADER, decode_access_token
from app.db.session import get_db
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token returned by POST /auth/login")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Not authenticated", code="not_authenticated", headers=BEARER_HEADER)
    user = db.get(User, decode_access_token(credentials.credentials))
    if user is None:
        raise UnauthorizedError("User no longer exists", code="invalid_token", headers=BEARER_HEADER)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise ForbiddenError("Admin privileges required", code="admin_required")
    return user


@dataclass
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    offset: int = Query(0, ge=0, description="Number of items to skip"),
) -> Pagination:
    return Pagination(limit=limit, offset=offset)
