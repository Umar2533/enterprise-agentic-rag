from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generate_secure_token, hash_password, hash_token
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_password_reset_token(db: Session, user_id: int) -> str:
    settings = get_settings()
    raw_token = generate_secure_token()
    reset_token = PasswordResetToken(
        user_id=user_id,
        token_hash=hash_token(raw_token),
        expires_at=utc_now()
        + timedelta(hours=settings.password_reset_token_expire_hours),
    )
    db.add(reset_token)
    db.commit()
    db.refresh(reset_token)
    return raw_token


def reset_password_with_token(db: Session, raw_token: str, new_password: str) -> bool:
    token_hash = hash_token(raw_token)
    stmt = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
    )
    reset_token = db.execute(stmt).scalar_one_or_none()
    if reset_token is None:
        return False

    now = utc_now()
    if ensure_aware(reset_token.expires_at) <= now:
        return False

    user = db.get(User, reset_token.user_id)
    if user is None:
        return False

    user.password_hash = hash_password(new_password)
    reset_token.used_at = now

    refresh_stmt = select(RefreshToken).where(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None),
    )
    refresh_tokens = db.execute(refresh_stmt).scalars().all()
    for refresh_token in refresh_tokens:
        if ensure_aware(refresh_token.expires_at) > now:
            refresh_token.revoked_at = now
            db.add(refresh_token)

    db.add(user)
    db.add(reset_token)
    db.commit()
    return True
