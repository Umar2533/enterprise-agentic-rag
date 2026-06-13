from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generate_secure_token, hash_token
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_email_verification_token(db: Session, user_id: int) -> str:
    settings = get_settings()
    raw_token = generate_secure_token()
    verification_token = EmailVerificationToken(
        user_id=user_id,
        token_hash=hash_token(raw_token),
        expires_at=utc_now()
        + timedelta(hours=settings.email_verification_token_expire_hours),
    )
    db.add(verification_token)
    db.commit()
    db.refresh(verification_token)
    return raw_token


def verify_email_token(db: Session, raw_token: str) -> User | None:
    token_hash = hash_token(raw_token)
    stmt = select(EmailVerificationToken).where(
        EmailVerificationToken.token_hash == token_hash,
        EmailVerificationToken.used_at.is_(None),
    )
    verification_token = db.execute(stmt).scalar_one_or_none()
    if verification_token is None:
        return None

    now = utc_now()
    if ensure_aware(verification_token.expires_at) <= now:
        return None

    user = verification_token.user
    if user is None:
        return None

    verification_token.used_at = now
    user.is_email_verified = True
    user.email_verified_at = now

    db.add(verification_token)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
