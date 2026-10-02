from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.models import User


def signup(db: Session, email: str, password: str) -> User:
    email = email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("Email is already registered", code="email_already_registered")

    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError("Email is already registered", code="email_already_registered")
    return user


@lru_cache
def _dummy_hash() -> str:
    return hash_password("not-a-real-password")


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    password_ok = verify_password(password, user.hashed_password if user else _dummy_hash())
    if user is None or not password_ok:
        raise UnauthorizedError("Incorrect email or password", code="invalid_credentials")
    return user
