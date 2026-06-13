import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_settings, limiter, settings
from app.core.security import create_access_token, validate_password_strength
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth_schema import (
    ForgotPasswordRequest,
    LogoutRequest,
    RefreshTokenRequest,
    ResetPasswordRequest,
    SignupResponse,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.auth.email_verification_service import (
    create_email_verification_token,
    verify_email_token,
)
from app.services.auth.password_reset_service import (
    create_password_reset_token,
    reset_password_with_token,
)
from app.services.auth.refresh_token_service import (
    create_refresh_token,
    get_valid_refresh_token,
    revoke_refresh_token,
)
from app.services.auth.user_service import (
    AccountLockedError,
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_by_id,
)
from app.services.audit import extract_request_meta, log_audit_event
from app.services.email.email_service import (
    build_password_reset_email,
    build_verification_email,
    send_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    cookie_settings = get_settings()
    if not cookie_settings.auth_cookie_enabled:
        return
    response.set_cookie(
        key=cookie_settings.access_cookie_name,
        value=access_token,
        max_age=cookie_settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=cookie_settings.auth_cookie_secure,
        samesite=cookie_settings.auth_cookie_samesite,
        path="/",
    )
    response.set_cookie(
        key=cookie_settings.refresh_cookie_name,
        value=refresh_token,
        max_age=cookie_settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=cookie_settings.auth_cookie_secure,
        samesite=cookie_settings.auth_cookie_samesite,
        path="/",
    )
    logger.debug("Auth cookies Set-Cookie headers present: %s", "set-cookie" in response.headers)


def _delete_auth_cookies(response: Response) -> None:
    cookie_settings = get_settings()
    if not cookie_settings.auth_cookie_enabled:
        return
    for cookie_name in (
        cookie_settings.access_cookie_name,
        cookie_settings.refresh_cookie_name,
    ):
        response.delete_cookie(
            key=cookie_name,
            path="/",
            secure=cookie_settings.auth_cookie_secure,
            samesite=cookie_settings.auth_cookie_samesite,
            httponly=True,
        )
    logger.debug("Auth cookies delete Set-Cookie headers present: %s", "set-cookie" in response.headers)


def _refresh_token_from_request(
    token_in: RefreshTokenRequest | LogoutRequest | None,
) -> str | None:
    return token_in.refresh_token if token_in else None


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(settings.auth_signup_rate_limit)
def signup(
    user_in: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> SignupResponse:
    try:
        validate_password_strength(user_in.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None

    if get_user_by_email(db, str(user_in.email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered.",
        )

    try:
        user = create_user(db, user_in)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered.",
        ) from None

    raw_token = create_email_verification_token(db, user.id)
    subject, body = build_verification_email(user.email, raw_token)
    settings = get_settings()
    email_status = send_email(user.email, subject, body)
    if not email_status.sent:
        logger.warning(
            "Verification email was not sent for user_id=%s: %s.",
            user.id,
            email_status.reason,
        )

    verification_hint = None
    if settings.environment.lower() == "development":
        verification_hint = (
            f"{settings.frontend_base_url.rstrip('/')}/verify-email?token={raw_token}"
        )

    response = SignupResponse.model_validate(user)
    response.message = "Account created. Please check your email to verify your account."
    response.verification_hint = verification_hint
    log_audit_event(
        db,
        "auth.signup.success",
        user_id=user.id,
        details={"email": user.email},
        **extract_request_meta(request),
    )
    return response


@router.post("/verify-email")
def verify_email(
    token_in: VerifyEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    user = verify_email_token(db, token_in.token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or already used verification token.",
        )

    log_audit_event(
        db,
        "auth.email_verified.success",
        user_id=user.id,
        details={"email": user.email},
        **extract_request_meta(request),
    )
    return {"success": True, "message": "Email verified successfully."}


@router.post("/forgot-password")
@limiter.limit(settings.forgot_password_rate_limit)
def forgot_password(
    password_in: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    settings = get_settings()
    response = {
        "success": True,
        "message": "If the account exists, reset instructions were sent.",
    }
    user = get_user_by_email(db, str(password_in.email))
    if user is not None:
        raw_token = create_password_reset_token(db, user.id)
        subject, body = build_password_reset_email(user.email, raw_token)
        email_status = send_email(user.email, subject, body)
        if not email_status.sent:
            logger.warning(
                "Password reset email was not sent for user_id=%s: %s.",
                user.id,
                email_status.reason,
            )

        if settings.environment.lower() == "development":
            response["reset_token"] = raw_token
            response["reset_link"] = (
                f"{settings.frontend_base_url.rstrip('/')}/reset-password?token={raw_token}"
            )

    log_audit_event(
        db,
        "auth.password_reset.requested",
        user_id=user.id if user is not None else None,
        details={"email": str(password_in.email).strip().lower()},
        **extract_request_meta(request),
    )
    return response


@router.post("/reset-password")
@limiter.limit(settings.forgot_password_rate_limit)
def reset_password(
    password_in: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    try:
        validate_password_strength(password_in.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None

    did_reset = reset_password_with_token(
        db,
        raw_token=password_in.token,
        new_password=password_in.new_password,
    )
    if not did_reset:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, expired, or already used password reset token.",
        )

    log_audit_event(
        db,
        "auth.password_reset.success",
        **extract_request_meta(request),
    )
    return {"success": True, "message": "Password reset successfully."}


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.auth_login_rate_limit)
def login(
    user_in: UserLogin,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = str(user_in.email).strip().lower()
    attempted_user = get_user_by_email(db, email)
    try:
        user = authenticate_user(db, email, user_in.password)
    except AccountLockedError:
        log_audit_event(
            db,
            "auth.login.locked",
            user_id=attempted_user.id if attempted_user is not None else None,
            status="failure",
            details={"email": email},
            **extract_request_meta(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account temporarily locked. Try again later.",
        ) from None

    if user is None:
        log_audit_event(
            db,
            "auth.login.failed",
            user_id=attempted_user.id if attempted_user is not None else None,
            status="failure",
            details={"email": email},
            **extract_request_meta(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_email_verified:
        log_audit_event(
            db,
            "auth.login.failed",
            user_id=user.id,
            status="failure",
            details={"email": email, "reason": "email_not_verified"},
            **extract_request_meta(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )

    if not user.is_active:
        log_audit_event(
            db,
            "auth.login.failed",
            user_id=user.id,
            status="failure",
            details={"email": email, "reason": "inactive_user"},
            **extract_request_meta(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive.",
        )

    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(
        db,
        user_id=user.id,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    log_audit_event(
        db,
        "auth.login.success",
        user_id=user.id,
        details={"email": user.email},
        **extract_request_meta(request),
    )
    _set_auth_cookies(response, access_token, refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user=user)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    request: Request,
    response: Response,
    token_in: RefreshTokenRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> TokenResponse:
    raw_refresh_token = _refresh_token_from_request(token_in)
    if not raw_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    stored_token = get_valid_refresh_token(db, raw_refresh_token)
    if stored_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    user = get_user_by_id(db, stored_token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    revoke_refresh_token(db, raw_refresh_token)
    rotated_refresh_token = create_refresh_token(
        db,
        user_id=user.id,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )
    access_token = create_access_token(subject=user.id)
    _set_auth_cookies(response, access_token, rotated_refresh_token)
    return TokenResponse(
        access_token=access_token,
        refresh_token=rotated_refresh_token,
        user=user,
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    token_in: LogoutRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> dict:
    raw_refresh_token = _refresh_token_from_request(token_in)
    stored_token = get_valid_refresh_token(db, raw_refresh_token) if raw_refresh_token else None
    if raw_refresh_token:
        revoke_refresh_token(db, raw_refresh_token)
    _delete_auth_cookies(response)
    log_audit_event(
        db,
        "auth.logout.success",
        user_id=stored_token.user_id if stored_token is not None else None,
        **extract_request_meta(request),
    )
    return {"success": True, "message": "Logged out successfully."}


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user
