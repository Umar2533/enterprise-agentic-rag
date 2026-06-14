from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from slowapi import Limiter
from slowapi.util import get_remote_address


ROOT_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT_DIR.parent

# Load project-level environment for code paths that still read os.environ.
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    app_name: str = Field(
        default="Enterprise Documents Agentic RAG System",
        validation_alias=AliasChoices("APP_NAME", "app_name"),
    )
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "environment"),
    )
    api_prefix: str = "/api/v1"
    backend_cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8501",
            "http://127.0.0.1:8501",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        validation_alias=AliasChoices(
            "BACKEND_CORS_ORIGINS",
            "CORS_ORIGINS",
            "FRONTEND_ORIGINS",
            "cors_origins",
        ),
    )
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"],
        validation_alias=AliasChoices("TRUSTED_HOSTS", "trusted_hosts"),
    )
    enable_https_redirect: bool = Field(
        default=False,
        validation_alias=AliasChoices("ENABLE_HTTPS_REDIRECT", "enable_https_redirect"),
    )
    security_headers_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SECURITY_HEADERS_ENABLED",
            "security_headers_enabled",
        ),
    )

    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    llm_provider: str = Field(
        default="auto",
        validation_alias=AliasChoices("LLM_PROVIDER", "llm_provider"),
    )
    local_test_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices("LOCAL_TEST_MODE", "local_test_mode"),
    )
    render_free_mvp: bool = Field(
        default=False,
        validation_alias=AliasChoices("RENDER_FREE_MVP", "render_free_mvp"),
    )
    openai_fallback_on_error: bool = Field(
        default=False,
        validation_alias=AliasChoices("OPENAI_FALLBACK_ON_ERROR", "openai_fallback_on_error"),
    )
    qdrant_url: str = Field(
        default="",
        validation_alias=AliasChoices("QDRANT_URL", "qdrant_url"),
    )
    qdrant_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("QDRANT_API_KEY", "qdrant_api_key"),
    )
    tavily_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("TAVILY_API_KEY", "tavily_api_key"),
    )
    database_url: str = Field(
        default=f"sqlite:///{ROOT_DIR / 'data' / 'app.db'}",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    backend_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BACKEND_API_KEY", "backend_api_key"),
    )
    primary_admin_email: str | None = Field(
        default=None,
        validation_alias=AliasChoices("PRIMARY_ADMIN_EMAIL", "primary_admin_email"),
    )
    primary_admin_emails_csv: str = Field(
        default="",
        validation_alias=AliasChoices("PRIMARY_ADMIN_EMAILS", "primary_admin_emails_csv"),
    )
    jwt_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "jwt_secret_key"),
    )
    jwt_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("JWT_ALGORITHM", "jwt_algorithm"),
    )
    access_token_expire_minutes: int = Field(
        default=30,
        validation_alias=AliasChoices(
            "ACCESS_TOKEN_EXPIRE_MINUTES",
            "access_token_expire_minutes",
        ),
    )
    refresh_token_expire_days: int = Field(
        default=7,
        validation_alias=AliasChoices(
            "REFRESH_TOKEN_EXPIRE_DAYS",
            "refresh_token_expire_days",
        ),
    )
    auth_cookie_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AUTH_COOKIE_ENABLED", "auth_cookie_enabled"),
    )
    access_cookie_name: str = Field(
        default="access_token",
        validation_alias=AliasChoices("ACCESS_COOKIE_NAME", "access_cookie_name"),
    )
    refresh_cookie_name: str = Field(
        default="refresh_token",
        validation_alias=AliasChoices("REFRESH_COOKIE_NAME", "refresh_cookie_name"),
    )
    auth_cookie_samesite: str = Field(
        default="lax",
        validation_alias=AliasChoices("AUTH_COOKIE_SAMESITE", "auth_cookie_samesite"),
    )
    auth_cookie_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("AUTH_COOKIE_SECURE", "auth_cookie_secure"),
    )
    rate_limit_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("RATE_LIMIT_ENABLED", "rate_limit_enabled"),
    )
    auth_login_rate_limit: str = Field(
        default="5/minute",
        validation_alias=AliasChoices(
            "AUTH_LOGIN_RATE_LIMIT",
            "auth_login_rate_limit",
        ),
    )
    auth_signup_rate_limit: str = Field(
        default="3/minute",
        validation_alias=AliasChoices(
            "AUTH_SIGNUP_RATE_LIMIT",
            "auth_signup_rate_limit",
        ),
    )
    forgot_password_rate_limit: str = Field(
        default="3/minute",
        validation_alias=AliasChoices(
            "FORGOT_PASSWORD_RATE_LIMIT",
            "forgot_password_rate_limit",
        ),
    )
    global_api_rate_limit: str = Field(
        default="100/minute",
        validation_alias=AliasChoices(
            "GLOBAL_API_RATE_LIMIT",
            "global_api_rate_limit",
        ),
    )
    max_login_attempts: int = Field(
        default=5,
        validation_alias=AliasChoices("MAX_LOGIN_ATTEMPTS", "max_login_attempts"),
    )
    account_lockout_minutes: int = Field(
        default=15,
        validation_alias=AliasChoices(
            "ACCOUNT_LOCKOUT_MINUTES",
            "account_lockout_minutes",
        ),
    )
    email_verification_token_expire_hours: int = Field(
        default=24,
        validation_alias=AliasChoices(
            "EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS",
            "email_verification_token_expire_hours",
        ),
    )
    password_reset_token_expire_hours: int = Field(
        default=1,
        validation_alias=AliasChoices(
            "PASSWORD_RESET_TOKEN_EXPIRE_HOURS",
            "password_reset_token_expire_hours",
        ),
    )
    password_min_length: int = Field(
        default=8,
        validation_alias=AliasChoices("PASSWORD_MIN_LENGTH", "password_min_length"),
    )
    frontend_base_url: str = Field(
        default="http://localhost:8501",
        validation_alias=AliasChoices("FRONTEND_BASE_URL", "frontend_base_url"),
    )
    mail_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("MAIL_ENABLED", "mail_enabled"),
    )
    mail_from: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAIL_FROM", "mail_from"),
    )
    mail_server: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAIL_SERVER", "mail_server"),
    )
    mail_port: int = Field(
        default=587,
        validation_alias=AliasChoices("MAIL_PORT", "mail_port"),
    )
    mail_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAIL_USERNAME", "mail_username"),
    )
    mail_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MAIL_PASSWORD", "mail_password"),
    )
    mail_use_tls: bool = Field(
        default=True,
        validation_alias=AliasChoices("MAIL_USE_TLS", "mail_use_tls"),
    )

    vector_db_provider: str = "qdrant"

    upload_dir: Path = ROOT_DIR / "data" / "uploads"
    temp_dir: Path = ROOT_DIR / "data" / "temp"
    memory_dir: Path = ROOT_DIR / "data" / "memory"
    max_upload_mb: int = 25
    max_upload_size_mb: int = Field(
        default=25,
        validation_alias=AliasChoices("MAX_UPLOAD_SIZE_MB", "max_upload_size_mb"),
    )
    allowed_extensions: list[str] = Field(
        default_factory=lambda: ["txt", "md", "pdf", "docx", "doc", "csv"]
    )

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        enable_decoding=False,
        extra="ignore",
    )

    @field_validator("backend_cors_origins", "trusted_hosts", "allowed_extensions", mode="before")
    @classmethod
    def split_csv_values(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @property
    def cors_origins(self) -> list[str]:
        return self.backend_cors_origins

    @property
    def primary_admin_emails(self) -> list[str]:
        emails = [
            item.strip().lower()
            for item in self.primary_admin_emails_csv.split(",")
            if item.strip()
        ]
        legacy_email = (self.primary_admin_email or "").strip().lower()
        if legacy_email:
            emails.append(legacy_email)
        return list(dict.fromkeys(emails))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()


def validate_production_settings() -> None:
    if settings.environment.lower() != "production":
        return

    if not settings.jwt_secret_key or len(settings.jwt_secret_key) < 32:
        raise RuntimeError("JWT_SECRET_KEY must be set to at least 32 characters in production.")
    if not settings.backend_api_key or len(settings.backend_api_key) < 32:
        raise RuntimeError("BACKEND_API_KEY must be set to at least 32 characters in production.")
    if "*" in settings.backend_cors_origins:
        raise RuntimeError("BACKEND_CORS_ORIGINS must not contain '*' in production.")
    if not settings.backend_cors_origins:
        raise RuntimeError("FRONTEND_ORIGINS must be set to explicit HTTPS domains in production.")
    insecure_origins = [
        origin
        for origin in settings.backend_cors_origins
        if not origin.lower().startswith("https://")
    ]
    if insecure_origins:
        raise RuntimeError("FRONTEND_ORIGINS must use HTTPS domains in production.")
    if settings.database_url.strip().lower().startswith("sqlite"):
        raise RuntimeError("DATABASE_URL must not use SQLite in production.")
    if settings.frontend_base_url.strip().lower().startswith("http://"):
        raise RuntimeError("FRONTEND_BASE_URL must use HTTPS in production.")
    if not settings.mail_enabled:
        raise RuntimeError("MAIL_ENABLED must be true in production.")
    missing_mail_settings = [
        name
        for name, value in {
            "MAIL_FROM": settings.mail_from,
            "MAIL_SERVER": settings.mail_server,
            "MAIL_USERNAME": settings.mail_username,
            "MAIL_PASSWORD": settings.mail_password,
        }.items()
        if not value
    ]
    if missing_mail_settings:
        raise RuntimeError(
            f"{', '.join(missing_mail_settings)} must be configured in production."
        )

# Backward-compatible module-level aliases for older import styles.
APP_NAME = settings.app_name
ENVIRONMENT = settings.environment
OPENAI_API_KEY = settings.openai_api_key
QDRANT_URL = settings.qdrant_url
QDRANT_API_KEY = settings.qdrant_api_key
TAVILY_API_KEY = settings.tavily_api_key
DATABASE_URL = settings.database_url
BACKEND_API_KEY = settings.backend_api_key
PRIMARY_ADMIN_EMAIL = settings.primary_admin_email
PRIMARY_ADMIN_EMAILS = settings.primary_admin_emails
JWT_SECRET_KEY = settings.jwt_secret_key
JWT_ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days
AUTH_COOKIE_ENABLED = settings.auth_cookie_enabled
ACCESS_COOKIE_NAME = settings.access_cookie_name
REFRESH_COOKIE_NAME = settings.refresh_cookie_name
AUTH_COOKIE_SAMESITE = settings.auth_cookie_samesite
AUTH_COOKIE_SECURE = settings.auth_cookie_secure
RATE_LIMIT_ENABLED = settings.rate_limit_enabled
AUTH_LOGIN_RATE_LIMIT = settings.auth_login_rate_limit
AUTH_SIGNUP_RATE_LIMIT = settings.auth_signup_rate_limit
FORGOT_PASSWORD_RATE_LIMIT = settings.forgot_password_rate_limit
GLOBAL_API_RATE_LIMIT = settings.global_api_rate_limit
MAX_LOGIN_ATTEMPTS = settings.max_login_attempts
ACCOUNT_LOCKOUT_MINUTES = settings.account_lockout_minutes
EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS = settings.email_verification_token_expire_hours
PASSWORD_RESET_TOKEN_EXPIRE_HOURS = settings.password_reset_token_expire_hours
PASSWORD_MIN_LENGTH = settings.password_min_length
FRONTEND_BASE_URL = settings.frontend_base_url
MAIL_ENABLED = settings.mail_enabled
MAIL_FROM = settings.mail_from
MAIL_SERVER = settings.mail_server
MAIL_PORT = settings.mail_port
MAIL_USERNAME = settings.mail_username
MAIL_PASSWORD = settings.mail_password
MAIL_USE_TLS = settings.mail_use_tls
BACKEND_CORS_ORIGINS = settings.backend_cors_origins
TRUSTED_HOSTS = settings.trusted_hosts
ENABLE_HTTPS_REDIRECT = settings.enable_https_redirect
SECURITY_HEADERS_ENABLED = settings.security_headers_enabled

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.global_api_rate_limit],
    enabled=settings.rate_limit_enabled,
)
