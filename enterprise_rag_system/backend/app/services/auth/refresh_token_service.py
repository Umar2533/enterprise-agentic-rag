from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import generate_secure_token, hash_token
from app.models.refresh_token import RefreshToken


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_refresh_token(
    db: Session,
    user_id: int,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> str:
    settings = get_settings()
    raw_token = generate_secure_token()
    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(raw_token),
        expires_at=utc_now() + timedelta(days=settings.refresh_token_expire_days),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)
    return raw_token


def get_valid_refresh_token(db: Session, raw_token: str) -> RefreshToken | None:
    token_hash = hash_token(raw_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    refresh_token = db.execute(stmt).scalar_one_or_none()
    if refresh_token is None:
        return None
    if refresh_token.revoked_at is not None:
        return None
    if ensure_aware(refresh_token.expires_at) <= utc_now():
        return None
    return refresh_token


def revoke_refresh_token(db: Session, raw_token: str) -> bool:
    refresh_token = get_valid_refresh_token(db, raw_token)
    if refresh_token is None:
        return False

    refresh_token.revoked_at = utc_now()
    db.add(refresh_token)
    db.commit()
    return True
