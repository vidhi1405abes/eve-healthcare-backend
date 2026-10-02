from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.docs import error_responses
from app.core.config import settings
from app.core.rate_limit import limit_auth_requests
from app.core.security import create_access_token
from app.db.session import get_db
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup",
    response_model=UserOut,
    status_code=201,
    summary="Create an account",
    description="Registers a new user. Emails are case-insensitive and must be unique. "
    "Rate limited per client IP. New users are never admins.",
    dependencies=[Depends(limit_auth_requests)],
    responses=error_responses(409, 422, 429),
)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> User:
    return auth_service.signup(db, payload.email, payload.password)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and get a JWT access token",
    description="Send the returned token as `Authorization: Bearer <token>`. Rate limited per client IP.",
    dependencies=[Depends(limit_auth_requests)],
    responses=error_responses(401, 422, 429),
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = auth_service.authenticate(db, payload.email, payload.password)
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.get(
    "/me",
    response_model=UserOut,
    summary="Current user",
    responses=error_responses(401),
)
def me(user: User = Depends(get_current_user)) -> User:
    return user
