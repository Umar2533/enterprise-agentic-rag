from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin, require_api_key
from app.core.config import settings
from app.db.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.services.audit import get_audit_logs

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_api_key), Depends(require_admin)],
)


class AdminUserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    role: str
    is_active: bool
    is_superuser: bool
    is_primary_admin: bool
    is_email_verified: bool
    failed_login_attempts: int
    last_failed_login_at: datetime | None = None
    account_locked_until: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def mark_configured_primary_admin(self):
        if self.email.lower() in settings.primary_admin_emails:
            self.is_primary_admin = True
        return self


class UserRoleUpdate(BaseModel):
    role: Literal["admin", "user"]


class UserActiveUpdate(BaseModel):
    is_active: bool


class AuditLogResponse(BaseModel):
    id: int
    event_type: str
    status: str
    user_id: int | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


def get_admin_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return user


def is_primary_admin(user: User) -> bool:
    email = (user.email or "").strip().lower()
    return bool(user.is_primary_admin) or email in settings.primary_admin_emails


def assert_can_change_role(actor: User, target: User, new_role: str) -> None:
    target_is_primary = is_primary_admin(target)
    if target_is_primary and new_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primary admin cannot be demoted.",
        )
    if target_is_primary and actor.id != target.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primary admin role cannot be modified by another admin.",
        )
    if actor.id == target.id and new_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot demote their own account.",
        )


def assert_can_change_active_status(actor: User, target: User, is_active: bool) -> None:
    target_is_primary = is_primary_admin(target)
    if target_is_primary and not is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primary admin cannot be deactivated.",
        )
    if target_is_primary and actor.id != target.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primary admin status cannot be modified by another admin.",
        )
    if is_active:
        return
    if actor.id == target.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot deactivate their own account.",
        )


@router.get("/status")
def admin_status():
    return {"success": True, "enabled": True, "message": "Admin APIs are enabled."}


@router.get("/audit-logs", response_model=list[AuditLogResponse])
def list_audit_logs(
    limit: int = 50,
    event_type: str | None = None,
    user_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    return get_audit_logs(
        db,
        limit=limit,
        event_type=event_type,
        user_id=user_id,
        status=status,
    )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.id)
    return list(db.execute(stmt).scalars().all())


@router.get("/users/{user_id}/status", response_model=AdminUserResponse)
def view_user_status(user_id: int, db: Session = Depends(get_db)) -> User:
    return get_admin_user_or_404(db, user_id)


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
def update_user_role(
    user_id: int,
    role_in: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    user = get_admin_user_or_404(db, user_id)
    assert_can_change_role(current_user, user, role_in.role)
    user.role = role_in.role
    user.is_superuser = role_in.role == "admin"
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}/active", response_model=AdminUserResponse)
def update_user_active_status(
    user_id: int,
    active_in: UserActiveUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    user = get_admin_user_or_404(db, user_id)
    assert_can_change_active_status(current_user, user, active_in.is_active)
    user.is_active = active_in.is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/unlock", response_model=AdminUserResponse)
def unlock_user_account(user_id: int, db: Session = Depends(get_db)) -> User:
    user = get_admin_user_or_404(db, user_id)
    user.failed_login_attempts = 0
    user.last_failed_login_at = None
    user.account_locked_until = None
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
