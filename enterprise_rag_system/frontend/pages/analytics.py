from collections import Counter
from datetime import datetime
from html import escape

import json
import os

import streamlit as st

from components.auth_panel import require_login
from components.layout import init_session_state, load_styles
from components.runtime_secrets import require_runtime_credentials
from components.sidebar import render_sidebar
from services.api_client import ApiClientError, cached_list_collections, cached_memory_stats, get_audit_logs, get_current_user
from services.api_client import (
    get_admin_users,
    unlock_admin_user,
    update_admin_user_role,
    update_admin_user_status,
)


def _render_workspace_loader(persistent: bool = False):
    loader_class = "workspace-loader workspace-loader-persistent" if persistent else "workspace-loader"
    return st.markdown(
        f"""
        <div class="{loader_class}" role="status" aria-live="polite" aria-label="Loading workspace">
          <div class="workspace-loader-progress"></div>
          <div class="workspace-loader-card">
            <span class="workspace-loader-spinner" aria-hidden="true"></span>
            <span class="workspace-loader-title">Loading...</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _safe_collections() -> tuple[list[dict], str]:
    try:
        payload = cached_list_collections()
        collections = payload.get("collections", [])
        return collections if isinstance(collections, list) else [], ""
    except ApiClientError as exc:
        return [], str(exc)


def _safe_memory() -> dict:
    try:
        return cached_memory_stats()
    except ApiClientError:
        return {}


def _chunk_count(item: dict) -> int:
    for key in ("chunk_count", "chunks", "vectors_count", "points_count"):
        try:
            return int(item.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _metric_card(title: str, value: str, note: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card analytics-metric">
          <span>{escape(title)}</span>
          <strong>{escape(value)}</strong>
          {f"<small>{escape(note)}</small>" if note else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _query_date(log: dict) -> str:
    raw = log.get("created_at") or ""
    try:
        return datetime.fromisoformat(raw).strftime("%b %d")
    except ValueError:
        return "Session"


def _source_count(log: dict) -> int:
    messages = log.get("messages", [])
    assistant = next((msg for msg in reversed(messages) if msg.get("role") == "assistant"), {})
    return len(assistant.get("sources", []) or [])


def _render_query_activity(query_logs: list[dict]) -> None:
    if not query_logs:
        return
    st.markdown('<div class="dashboard-card analytics-panel">', unsafe_allow_html=True)
    counts = Counter(_query_date(log) for log in query_logs)
    dated_counts = {label: count for label, count in sorted(counts.items()) if label != "Session"}
    if len(dated_counts) >= 2:
        st.line_chart({"Queries": dated_counts}, height=170)
    else:
        st.markdown(
            '<div class="empty-state compact"><div>'
            '<strong>Query trend unavailable</strong>'
            '<span>Trend appears after queries have timestamps across multiple days.</span>'
            '</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
   



def _render_collection_coverage(collections: list[dict], collection_error: str = "") -> None:
    active_collection = st.session_state.get("active_collection") or "None"
    total_chunks = sum(_chunk_count(item) for item in collections)
    providers = sorted({item.get("embedding_provider") or "unknown" for item in collections})
    provider_label = ", ".join(providers[:2]) if providers else "None"
    if len(providers) > 2:
        provider_label = f"{provider_label} +{len(providers) - 2}"

    if collection_error:
        st.markdown(
            f"""
            <div class="dashboard-card analytics-panel coverage-panel">
              <h3>Collection Coverage</h3>
              <div class="empty-state compact">
                <div>
                  <strong>Coverage unavailable</strong>
                  <span>{escape(collection_error)}</span>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="dashboard-card analytics-panel coverage-panel">
          <h3>Collection Coverage</h3>
          <div class="analytics-summary-grid">
            <div class="analytics-summary-item">
              <span>My collections</span>
              <strong>{len(collections):,}</strong>
            </div>
            <div class="analytics-summary-item">
              <span>Indexed chunks</span>
              <strong>{total_chunks:,}</strong>
            </div>
            <div class="analytics-summary-item">
              <span>Embedding providers</span>
              <strong>{escape(provider_label)}</strong>
            </div>
            <div class="analytics-summary-item">
              <span>Active collection</span>
              <strong>{escape(str(active_collection))}</strong>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_recent_logs(query_logs: list[dict]) -> None:
    if not query_logs:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(
            """
            <div class="dashboard-card analytics-panel recent-panel">
              <h3>Recent Queries</h3>
              <div class="empty-state compact">
                <div>
                  <strong>No recent queries</strong>
                  <span>Session queries will appear here after chat responses complete.</span>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    rows = []
    for log in reversed(query_logs[-6:]):
        title = escape(str(log.get("title") or "Untitled query"))
        collection = escape(str(log.get("collection") or "No collection"))
        rows.append(
            f'<div class="analytics-log-row"><div>{title}</div><span>{collection}</span></div>'
        )
    st.markdown(
        f'<div class="dashboard-card analytics-panel recent-panel">'
        f'<h3>Recent Queries</h3>{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


def _render_locked_state() -> None:
    st.markdown(
        """
        <div class="dashboard-card analytics-locked">
          <div class="lock-icon">API</div>
          <div>
            <h3>Analytics unavailable</h3>
            <p>Configure API keys to load query analytics and collection coverage.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/settings.py", label="Open Settings")


def _current_auth_user():
    user = st.session_state.get("auth_user") or {}
    has_identity_fields = _user_value(user, "role") is not None or _user_value(user, "is_superuser") is not None
    if (not user or not has_identity_fields) and st.session_state.get("auth_token"):
        user = get_current_user() or st.session_state.get("auth_user") or {}
    return user


def _user_value(user, key: str, default=None):
    if isinstance(user, dict):
        return user.get(key, default)
    return getattr(user, key, default)


def _is_admin_user(user) -> bool:
    role = _user_value(user, "role")
    if role is not None and hasattr(role, "value") and not isinstance(role, str):
        role = role.value
    is_superuser = _user_value(user, "is_superuser", False)
    return (str(role or "").lower() == "admin") or is_superuser is True


def _is_development_mode() -> bool:
    environment = (
        os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("RAG_ENV")
        or os.getenv("STREAMLIT_ENV")
        or "development"
    ).lower()
    return environment in {"development", "dev", "local"}


def _render_admin_debug(user) -> None:
    if not _is_development_mode():
        return
    email = _user_value(user, "email", "-") or "-"
    role = _user_value(user, "role", "-") or "-"
    if hasattr(role, "value") and not isinstance(role, str):
        role = role.value
    is_superuser = bool(_user_value(user, "is_superuser", False))
    st.caption(
        f"Admin debug: email={escape(str(email))} | role={escape(str(role))} | is_superuser={is_superuser}"
    )


def _admin_error_message(exc: ApiClientError) -> str:
    message = str(exc).strip()
    if exc.status_code == 401 or "401" in message:
        return "Your admin session is missing or expired. Please login again as admin."
    if exc.status_code == 403 or "403" in message:
        return "This protected admin action is not allowed."
    return message or "Admin data could not be loaded."


def _parse_user_id(raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("User ID must be a number.") from exc
    if parsed < 1:
        raise ValueError("User ID must be a positive number.")
    return parsed


def _is_auth_event(log: dict) -> bool:
    event_type = str(log.get("event_type") or "").lower()
    return "auth" in event_type or "login" in event_type or "logout" in event_type


def _redact_sensitive(value):
    sensitive_fragments = ("token", "password", "secret", "api_key", "apikey", "authorization", "hash")
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            key_text = str(key)
            if any(fragment in key_text.lower() for fragment in sensitive_fragments):
                clean[key_text] = "[redacted]"
            else:
                clean[key_text] = _redact_sensitive(item)
        return clean
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _safe_details(details) -> str:
    if details in ({}, [], None, ""):
        return ""
    sanitized = _redact_sensitive(details)
    if isinstance(sanitized, dict):
        return ", ".join(f"{key}: {value}" for key, value in sorted(sanitized.items()))
    if isinstance(sanitized, list):
        return "; ".join(str(item) for item in sanitized)
    return str(sanitized)


def _audit_table_rows(logs: list[dict]) -> list[dict]:
    rows = []
    for log in logs:
        rows.append(
            {
                "created_at": str(log.get("created_at") or ""),
                "event_type": str(log.get("event_type") or ""),
                "status": str(log.get("status") or ""),
                "user_id": "" if log.get("user_id") is None else str(log.get("user_id")),
                "ip_address": str(log.get("ip_address") or ""),
                "resource_type": str(log.get("resource_type") or ""),
                "resource_id": str(log.get("resource_id") or ""),
                "details": _safe_details(log.get("details")),
            }
        )
    return rows


def _bool_label(value) -> str:
    return "Yes" if value is True else "No"


def _current_user_id(user) -> int | None:
    raw_id = _user_value(user, "id")
    if raw_id is None or raw_id == "":
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _is_locked_user(user: dict) -> bool:
    try:
        failed_attempts = int(user.get("failed_login_attempts") or 0)
    except (TypeError, ValueError):
        failed_attempts = 0
    return bool(user.get("account_locked_until")) or failed_attempts > 0


def _is_primary_admin_record(user: dict) -> bool:
    return user.get("is_primary_admin") is True


def _admin_section(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <section class="admin-dashboard-section">
          <div class="section-title">
            <div>
              <h3>{escape(title)}</h3>
              {f"<p>{escape(subtitle)}</p>" if subtitle else ""}
            </div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def _load_admin_users() -> tuple[list[dict], str]:
    try:
        return get_admin_users(), ""
    except ApiClientError as exc:
        return [], _admin_error_message(exc)


def _load_filtered_audit_logs() -> tuple[list[dict], str]:
    try:
        user_id = _parse_user_id(str(st.session_state.get("audit_filter_user_id", "")))
        logs = get_audit_logs(
            limit=int(st.session_state.get("audit_filter_limit", 50)),
            event_type=str(st.session_state.get("audit_filter_event_type", "")),
            status=str(st.session_state.get("audit_filter_status", "all")),
            user_id=user_id,
        )
        return logs, ""
    except (ApiClientError, ValueError) as exc:
        if isinstance(exc, ApiClientError):
            return [], _admin_error_message(exc)
        return [], str(exc)


def _admin_user_rows(users: list[dict]) -> list[dict]:
    return [
        {
            "email": user.get("email") or "",
            "full_name": user.get("full_name") or "",
            "role": user.get("role") or "",
            "active": _bool_label(user.get("is_active")),
            "email_verified": _bool_label(user.get("is_email_verified")),
            "failed_login_attempts": int(user.get("failed_login_attempts") or 0),
            "locked_until": str(user.get("account_locked_until") or ""),
            "primary_admin": _bool_label(_is_primary_admin_record(user)),
        }
        for user in users
    ]


def _security_overview_metrics(users: list[dict], audit_logs: list[dict]) -> list[tuple[str, str, str]]:
    active_count = sum(1 for user in users if user.get("is_active") is True)
    admin_count = sum(1 for user in users if str(user.get("role") or "").lower() == "admin" or user.get("is_superuser") is True)
    locked_count = sum(1 for user in users if _is_locked_user(user))
    unverified_count = sum(1 for user in users if user.get("is_email_verified") is not True)
    return [
        ("Total users", f"{len(users):,}", "Real accounts"),
        ("Active users", f"{active_count:,}", "Enabled"),
        ("Locked users", f"{locked_count:,}", "Locked or failed"),
        ("Unverified users", f"{unverified_count:,}", "Email pending"),
        ("Admin users", f"{admin_count:,}", "Role/superuser"),
        ("Audit logs loaded", f"{len(audit_logs):,}", "Current filter"),
    ]


def _handle_admin_action(action_label: str, action) -> bool:
    try:
        action()
        st.success(f"{action_label} completed.")
        return True
    except ApiClientError as exc:
        st.error(_admin_error_message(exc))
        with st.expander("Technical details", expanded=False):
            st.code(str(exc))
        return False


def _render_admin_user_actions(user: dict, current_admin_id: int | None) -> None:
    user_id = int(user.get("id") or 0)
    if not user_id:
        return
    email = str(user.get("email") or f"User {user_id}")
    full_name = str(user.get("full_name") or "No name")
    role = str(user.get("role") or "user").lower()
    is_active = user.get("is_active") is True
    is_self = current_admin_id == user_id
    is_primary = _is_primary_admin_record(user)
    locked = _is_locked_user(user)
    status_label = "Active" if is_active else "Inactive"
    lock_label = "Locked" if locked else "Unlocked"
    verified_label = "Verified" if user.get("is_email_verified") is True else "Unverified"

    with st.container(border=True):
        identity_col, badges_col = st.columns([0.58, 0.42], gap="small")
        with identity_col:
            if is_primary:
                st.caption("LOCK")
            st.write(f"**{email}**")
            st.caption(f"ID {user_id} - {full_name}")
        with badges_col:
            badges = [role, status_label, lock_label, verified_label]
            if is_primary:
                badges.append("Protected Primary Admin")
            st.write("  ".join(f"`{badge}`" for badge in badges))

    if is_primary:
        st.markdown(
            """
            <div class="admin-protected-box">
              <strong>Protected owner account</strong>
              <span>Protected owner account. Recovery requires direct server/database access.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    col_unlock, col_status, col_role, col_apply = st.columns([0.2, 0.24, 0.28, 0.28], gap="small")
    with col_unlock:
        if st.button("Unlock", key=f"admin_unlock_user_{user_id}", disabled=not locked, width="stretch"):
            if _handle_admin_action("Unlock user", lambda: unlock_admin_user(user_id)):
                st.rerun()
    with col_status:
        target_active = not is_active
        disabled = is_primary or (is_self and not target_active)
        action_text = "Deactivate" if is_active else "Activate"
        if st.button(action_text, key=f"admin_toggle_user_{user_id}", disabled=disabled, width="stretch"):
            if disabled:
                st.warning("This account is protected from status changes.")
            elif _handle_admin_action(action_text, lambda: update_admin_user_status(user_id, target_active)):
                st.rerun()
        if disabled:
            st.caption("Status protected.")
    with col_role:
        selected_role = st.selectbox(
            "Role",
            ["user", "admin"],
            index=1 if role == "admin" else 0,
            key=f"admin_role_select_{user_id}",
            label_visibility="collapsed",
            disabled=is_primary,
        )
    with col_apply:
        demotes_self = is_self and selected_role != "admin"
        demotes_primary = is_primary and selected_role != "admin"
        role_disabled = selected_role == role or demotes_self or demotes_primary
        if st.button("Update role", key=f"admin_update_role_{user_id}", disabled=role_disabled, width="stretch"):
            if _handle_admin_action("Role update", lambda: update_admin_user_role(user_id, selected_role)):
                st.rerun()
        if demotes_self:
            st.caption("Self-demotion blocked.")
        elif demotes_primary:
            st.caption("Primary admin demotion blocked.")


def _render_security_overview(
    users: list[dict],
    audit_logs: list[dict],
    users_error: str,
    audit_error: str,
    show_header: bool = True,
) -> None:
    if show_header:
        st.markdown("<br>", unsafe_allow_html=True)
        _admin_section("Security Overview", "Live account and audit posture.")
    if users_error:
        st.error(users_error)
    if audit_error:
        st.error(audit_error)
    cols = st.columns(6, gap="small")
    for col, metric in zip(cols, _security_overview_metrics(users, audit_logs)):
        with col:
            _metric_card(*metric)


def _render_admin_user_management(user, users: list[dict], users_error: str, show_header: bool = True) -> None:
    if show_header:
        _admin_section("User Management", "Review access, protect owners, and manage account state.")
    action_cols = st.columns([0.82, 0.18], gap="small")
    with action_cols[1]:
        st.button("Refresh users", key="admin_users_refresh", width="stretch")

    if users_error:
        st.error(users_error)
        return

    if not users:
        st.markdown(
            '<div class="empty-state compact admin-users-empty"><div><strong>No users found</strong><span>The admin users endpoint returned no accounts.</span></div></div>',
            unsafe_allow_html=True,
        )
        return

    cols = st.columns(4, gap="small")
    user_metrics = _security_overview_metrics(users, [])[:4]
    for col, metric in zip(cols, user_metrics):
        with col:
            _metric_card(*metric)

    st.dataframe(
        _admin_user_rows(users),
        hide_index=True,
        width="stretch",
        column_order=[
            "email",
            "full_name",
            "role",
            "active",
            "email_verified",
            "failed_login_attempts",
            "locked_until",
            "primary_admin",
        ],
    )

    current_admin_id = _current_user_id(user)
    st.markdown('<div class="admin-user-actions-list">', unsafe_allow_html=True)
    for admin_user in users:
        _render_admin_user_actions(admin_user, current_admin_id)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_admin_access_required() -> None:
    st.markdown(
        """
        <div class="dashboard-card admin-audit-access">
          <strong>Admin access required.</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_admin_audit_dashboard(logs: list[dict], audit_error: str, show_header: bool = True) -> None:
    if show_header:
        _admin_section("Audit Logs", "Review administrative security events from the backend audit log.")
    with st.container(border=True):
        filter_cols = st.columns([0.16, 0.32, 0.2, 0.2, 0.12], gap="small")
        with filter_cols[0]:
            limit = st.selectbox("Limit", [25, 50, 100, 250, 500], index=1, key="audit_filter_limit")
        with filter_cols[1]:
            event_type = st.text_input("Event type", key="audit_filter_event_type", placeholder="auth.login")
        with filter_cols[2]:
            status = st.selectbox("Status", ["all", "success", "failure"], key="audit_filter_status")
        with filter_cols[3]:
            user_id_raw = st.text_input("User ID", key="audit_filter_user_id", placeholder="Optional")
        with filter_cols[4]:
            st.write("")
            st.button("Refresh", key="audit_refresh", width="stretch")

    if audit_error:
        st.error(audit_error)
        with st.expander("Technical details", expanded=False):
            st.code(audit_error)
        return

    failed_auth = sum(1 for log in logs if _is_auth_event(log) and str(log.get("status") or "").lower() == "failure")
    successful_auth = sum(1 for log in logs if _is_auth_event(log) and str(log.get("status") or "").lower() == "success")
    latest_event = str(logs[0].get("created_at") or "-") if logs else "-"
    audit_metrics = [
        ("Total logs loaded", f"{len(logs):,}", "Current filter"),
        ("Failed auth events", f"{failed_auth:,}", "Status failure"),
        ("Successful auth events", f"{successful_auth:,}", "Status success"),
        ("Latest event time", latest_event, "Newest loaded"),
    ]

    cols = st.columns(4, gap="small")
    for col, metric in zip(cols, audit_metrics):
        with col:
            _metric_card(*metric)

    if not logs:
        st.markdown(
            '<div class="empty-state compact admin-audit-empty"><div><strong>No audit logs found</strong><span>Adjust filters or refresh after backend activity.</span></div></div>',
            unsafe_allow_html=True,
        )
        return

    st.dataframe(
        _audit_table_rows(logs),
        hide_index=True,
        width="stretch",
        column_order=[
            "created_at",
            "event_type",
            "status",
            "user_id",
            "ip_address",
            "resource_type",
            "resource_id",
            "details",
        ],
    )


def _render_admin_dashboard() -> None:
    user = _current_auth_user()
    if not _is_admin_user(user):
        return

    users, users_error = _load_admin_users()
    audit_logs, audit_error = _load_filtered_audit_logs()
    st.markdown("<br>", unsafe_allow_html=True)
    with st.expander("Security Overview", expanded=False):
        _render_security_overview(users, audit_logs, users_error, audit_error, show_header=False)
    with st.expander("User Management", expanded=False):
        _render_admin_user_management(user, users, users_error, show_header=False)
    with st.expander("Audit Logs", expanded=False):
        _render_admin_audit_dashboard(audit_logs, audit_error, show_header=False)


st.set_page_config(page_title="Analytics | Enterprise RAG", page_icon="R", layout="wide")
load_styles()
_render_workspace_loader()
init_session_state()

if not require_login("Analytics"):
    st.stop()

require_runtime_credentials("analytics")
render_sidebar("Analytics")
st.markdown('<div class="rag-page-root analytics-page-root"></div>', unsafe_allow_html=True)

st.markdown(
    """
    <style>
      .analytics-header {
        border-bottom: 1px solid #e5eaf3;
        margin-bottom: 0.35rem;
        padding: 0.2rem 0 0.45rem;
      }
      .block-container:has(.analytics-page-root) {
        max-width: 1180px !important;
        padding-left: 1.4rem !important;
        padding-right: 1.4rem !important;
      }
      .analytics-header h1 {
        color: #0f1b3d;
        font-size: 1.55rem;
        line-height: 1.15;
        margin: 0;
        font-weight: 820;
      }
      .analytics-header p {
        color: #60708f;
        font-size: 0.92rem;
        margin: 0.32rem 0 0;
      }
      .block-container:has(.analytics-page-root) [data-testid="stExpander"] {
        border-color: #dbe4f0 !important;
        border-radius: 8px !important;
        box-shadow: none !important;
      }
      .block-container:has(.analytics-page-root) [data-testid="stExpander"] summary {
        min-height: 34px !important;
        padding: 0.38rem 0.62rem !important;
      }
      .block-container:has(.analytics-page-root) [data-testid="stExpander"] summary p {
        color: #0f1b3d !important;
        font-size: 0.84rem !important;
        font-weight: 780 !important;
      }
      .analytics-metric {
        min-height: 68px !important;
        padding: 0.68rem 0.74rem !important;
      }
      .analytics-metric strong {
        font-size: 1.16rem !important;
        overflow-wrap: anywhere;
      }
      .analytics-panel {
        padding: 0.35rem 0.45rem !important;
        min-height: auto !important;
      }
      .analytics-panel h3 {
        font-size: 0.88rem !important;
        margin: 0 0 0.28rem !important;
        line-height: 1.15 !important;
      }
      .coverage-panel {
        min-height: auto !important;
      }
      .analytics-summary-grid {
        display: grid;
        gap: 0.25rem;
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .analytics-summary-item {
        background: #f8fafc;
        border: 1px solid #e6edf7;
        border-radius: 8px;
        padding: 0.38rem 0.46rem;
      }
      .analytics-summary-item span {
        color: #64748b;
        display: block;
        font-size: 0.74rem;
        font-weight: 700;
        margin-bottom: 0.12rem;
      }
      .analytics-summary-item strong {
        color: #0f1b3d;
        display: inline-block;
        font-size: 0.92rem;
        line-height: 1.25;
        overflow-wrap: anywhere;
      }
      .analytics-locked {
        align-items: center;
        display: flex;
        gap: 0.9rem;
        margin-top: 1rem;
        max-width: 760px;
        padding: 1.05rem !important;
      }
      .analytics-locked .lock-icon {
        align-items: center;
        background: #eef2ff;
        border: 1px solid #dbe4ff;
        border-radius: 8px;
        color: #4338ca;
        display: flex;
        flex: 0 0 44px;
        font-size: 0.78rem;
        font-weight: 850;
        height: 44px;
        justify-content: center;
      }
      .analytics-locked h3 {
        color: #0f1b3d;
        font-size: 1.05rem;
        margin: 0 0 0.2rem;
      }
      .analytics-locked p {
        color: #60708f;
        margin: 0;
      }
      .analytics-log-row {
        padding: 0.58rem 0;
        border-bottom: 1px solid #eef2f8;
      }
      .analytics-log-row div {
        color: #0f1b3d;
        font-size: 0.86rem;
        font-weight: 780;
        line-height: 1.25;
      }
      .analytics-log-row span {
        color: #60708f;
        display: block;
        font-size: 0.76rem;
        margin-top: 0.12rem;
      }
      .empty-state.compact {
        min-height: auto !important;
        padding: 0.36rem 0.42rem;
      }
      .empty-state.compact strong {
        font-size: 0.84rem;
        margin-bottom: 0.08rem;
      }
      .empty-state.compact span {
        font-size: 0.78rem;
        line-height: 1.25;
      }
      @media (max-width: 900px) {
        .block-container:has(.analytics-page-root) {
          padding-left: 0.9rem !important;
          padding-right: 0.9rem !important;
        }
        .analytics-summary-grid {
          grid-template-columns: 1fr;
        }
        .analytics-locked {
          align-items: flex-start;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <section class="analytics-header">
      <h1>Analytics</h1>
    </section>
    """,
    unsafe_allow_html=True,
)

with st.expander("Page Notes", expanded=False):
    st.markdown(
        "Track session queries, retrieved context, collection coverage, account posture, and audit events."
    )

collections, collection_error = _safe_collections()
query_logs = st.session_state.get("query_logs", [])
retrieved_chunks = sum(_source_count(log) for log in query_logs)

if collection_error:
    st.markdown(
        f"""
        <div class="dashboard-card" style="border-color:#fecaca; background:#fff8f8; margin-bottom:0.75rem;">
          <h3>Analytics source unavailable</h3>
          <p>{escape(collection_error)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

active_collection = st.session_state.get("active_collection") or "None"
backend_status = "Issue" if collection_error else "Online"

metrics = [
    ("Session Queries", f"{len(query_logs):,}", "This browser session"),
    ("My Collections", f"{len(collections):,}", "Current account"),
    ("Active Collection", str(active_collection), "Runtime selection"),
    ("Backend Status", backend_status, "Collections service"),
]

cols = st.columns(4, gap="small")
for col, metric in zip(cols, metrics):
    with col:
        _metric_card(*metric)

main_col, side_col = st.columns([0.64, 0.36], gap="medium")
with main_col:
    _render_query_activity(query_logs)
    _render_collection_coverage(collections, collection_error)

with side_col:
    _render_recent_logs(query_logs)

_render_admin_dashboard()
