import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)

COMMON_PASSWORDS = {
    "password",
    "password123",
    "123456",
    "12345678",
    "admin",
    "admin123",
    "qwerty",
}
SPECIAL_CHARACTERS = set("!@#$%^&*()_+-=[]{}|;:,.<>?")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    if len(password) < settings.password_min_length:
        raise ValueError(
            f"Password must be at least {settings.password_min_length} characters long."
        )
    if password.strip().lower() in COMMON_PASSWORDS:
        raise ValueError("Password is too common.")
    if not any(char.isupper() for char in password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not any(char.islower() for char in password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain at least one number.")
    if not any(char in SPECIAL_CHARACTERS for char in password):
        raise ValueError("Password must contain at least one special character.")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def generate_secure_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    subject: str | int,
    expires_delta: timedelta | None = None,
) -> str:
    from app.core.config import get_settings

    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict | None:
    from app.core.config import get_settings

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        return None
