from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth_schema import UserCreate


class AccountLockedError(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == normalize_email(email))
    return db.execute(stmt).scalar_one_or_none()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    stmt = select(User).where(User.id == user_id)
    return db.execute(stmt).scalar_one_or_none()


def create_user(db: Session, user_in: UserCreate) -> User:
    user = User(
        email=normalize_email(str(user_in.email)),
        password_hash=hash_password(user_in.password),
        full_name=user_in.full_name,
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def reset_login_failures(db: Session, user: User) -> None:
    user.failed_login_attempts = 0
    user.last_failed_login_at = None
    user.account_locked_until = None
    db.add(user)
    db.commit()


def record_failed_login(db: Session, user: User) -> None:
    settings = get_settings()
    now = utc_now()
    user.failed_login_attempts += 1
    user.last_failed_login_at = now
    if user.failed_login_attempts >= settings.max_login_attempts:
        user.account_locked_until = now + timedelta(
            minutes=settings.account_lockout_minutes
        )
    db.add(user)
    db.commit()


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if user is None:
        return None

    now = utc_now()
    if user.account_locked_until is not None:
        locked_until = ensure_aware(user.account_locked_until)
        if locked_until > now:
            raise AccountLockedError
        reset_login_failures(db, user)

    if not verify_password(password, user.password_hash):
        record_failed_login(db, user)
        return None

    if (
        user.failed_login_attempts
        or user.last_failed_login_at is not None
        or user.account_locked_until is not None
    ):
        reset_login_failures(db, user)

    return user
