import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.audit_log import AuditLog


logger = logging.getLogger(__name__)
SENSITIVE_DETAIL_KEYS = {
    "api_key",
    "authorization",
    "jwt",
    "password",
    "refresh_token",
    "secret",
    "token",
    "token_hash",
}


def log_audit_event(
    db: Session,
    event_type: str,
    user_id: int | None = None,
    status: str = "success",
    ip_address: str | None = None,
    user_agent: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    try:
        audit_log = AuditLog(
            user_id=user_id,
            event_type=event_type,
            status=status,
            ip_address=ip_address,
            user_agent=user_agent,
            resource_type=resource_type,
            resource_id=resource_id,
            details=_sanitize_details(details),
        )
        db.add(audit_log)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Failed to write audit log event_type=%s.", event_type)


def extract_request_meta(request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("User-Agent"),
    }


def get_audit_logs(
    db: Session,
    limit: int = 50,
    event_type: str | None = None,
    user_id: int | None = None,
    status: str | None = None,
) -> list[AuditLog]:
    stmt = select(AuditLog)
    if event_type:
        stmt = stmt.where(AuditLog.event_type == event_type)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if status:
        stmt = stmt.where(AuditLog.status == status)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(max(1, min(limit, 500)))
    return list(db.execute(stmt).scalars().all())


def _sanitize_details(details: dict | None) -> dict | None:
    if details is None:
        return None
    return _sanitize_mapping(details)


def _sanitize_mapping(value: Mapping[str, Any]) -> dict:
    sanitized = {}
    for key, item in value.items():
        normalized_key = str(key).lower()
        if any(sensitive_key in normalized_key for sensitive_key in SENSITIVE_DETAIL_KEYS):
            sanitized[key] = "[REDACTED]"
        elif isinstance(item, Mapping):
            sanitized[key] = _sanitize_mapping(item)
        elif isinstance(item, list):
            sanitized[key] = [_sanitize_list_item(list_item) for list_item in item]
        else:
            sanitized[key] = item
    return sanitized


def _sanitize_list_item(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, list):
        return [_sanitize_list_item(item) for item in value]
    return value
