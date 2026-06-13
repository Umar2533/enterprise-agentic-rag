from __future__ import annotations

import html

import streamlit as st

from services.api_client import (
    ApiClientError,
    forgot_password,
    get_current_user,
    login_user,
    logout_user,
    refresh_access_token,
    restore_browser_auth_session,
    reset_password,
    signup_user,
    verify_email,
)


__all__ = [
    "ensure_auth_state",
    "handle_email_verification_query",
    "is_authenticated",
    "render_fullscreen_auth_gate",
    "render_settings_auth_panel",
    "render_sidebar_auth_card",
    "render_verification_page",
    "require_login",
]


def ensure_auth_state() -> None:
    st.session_state.setdefault("auth_token", "")
    st.session_state.setdefault("auth_refresh_token", "")
    st.session_state.setdefault("auth_user", {})
    st.session_state.setdefault("auth_error", "")
    st.session_state.setdefault("auth_notice_reason", "")
    st.session_state.setdefault("auth_checked_token", "")
    st.session_state.setdefault("_login_in_progress", False)
    st.session_state.setdefault("_login_submit_consumed", False)
    st.session_state.setdefault("_auth_action_feedback_mode", "")
    st.session_state.setdefault("_auth_action_feedback_kind", "")
    st.session_state.setdefault("_auth_action_feedback_message", "")
    current_url = _current_page_url()
    if st.session_state.get("_auth_panel_url") != current_url:
        st.session_state["_auth_panel_url"] = current_url
        st.session_state.pop("_auth_panel_active_location", None)
    if st.session_state.get("auth_user"):
        st.session_state.pop("_auth_panel_active_location", None)


def handle_email_verification_query(location: str = "fullscreen") -> bool:
    token = _query_param("token")
    if not token:
        return False

    render_verification_page(location=location, token=token)
    return True


def render_verification_page(location: str = "verify_page", token: str | None = None) -> None:
    ensure_auth_state()
    token = (token or _query_param("token")).strip()
    st.markdown('<div class="verify-email-page-root"></div>', unsafe_allow_html=True)
    with st.container(key=f"{location}_email_verification_panel"):
        st.markdown(
            """
            <div class="auth-panel-heading">
              <span>Email Verification</span>
              <h3>Verify Your Account</h3>
              <p>Complete verification, then return to the login tab.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not token:
            _auth_notice(
                "error",
                "Verification link is missing a token.",
                "Open the full verification link from your email.",
            )
            _render_login_return(location)
            return

        result_key = f"email_verification_result_{token}"
        if result_key not in st.session_state:
            try:
                verify_email(token)
                st.session_state[result_key] = {
                    "ok": True,
                    "message": "Email verified successfully. Please login.",
                }
                _set_auth_tabs("Login")
            except ApiClientError as exc:
                st.session_state[result_key] = {
                    "ok": False,
                    "message": _clean_auth_message(str(exc)),
                }

        result = st.session_state[result_key]
        if result.get("ok"):
            _auth_notice("success", "Email verified successfully. Please login.")
        else:
            _auth_notice("error", result.get("message") or "Email verification failed.")
        _render_login_return(location)


def render_sidebar_auth_card() -> None:
    ensure_auth_state()
    _refresh_current_user_once()
    user = st.session_state.get("auth_user") or {}

    with st.container(key="auth_sidebar_panel"):
        st.markdown('<div class="auth-mini-kicker">Account</div>', unsafe_allow_html=True)
        if user:
            _render_current_user(user, compact=True)
            st.caption("Session refreshes silently while you work.")
            if st.button("Logout", key="sidebar_auth_logout", width="stretch"):
                logout_user()
                st.rerun()
        else:
            st.markdown(
                """
                <div class="auth-sidebar-entry">
                  <strong>Secure workspace</strong>
                  <span>Sign in to unlock chat, upload, collections, and analytics.</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            _render_auth_tabs("sidebar")


def render_settings_auth_panel() -> None:
    ensure_auth_state()
    _refresh_current_user_once()
    user = st.session_state.get("auth_user") or {}

    with st.container(key="auth_settings_panel"):
        st.markdown(
            """
            <div class="auth-panel-heading">
              <span>Secure Access</span>
              <h3>Account Access</h3>
              <p>JWT session is stored only in this Streamlit session. Tokens are never displayed.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if user:
            _render_settings_account_summary(user)
            st.caption("Session refreshes silently while you work. Tokens are never shown.")
            if st.button("Refresh Session", key="settings_auth_refresh", width="stretch"):
                if refresh_access_token():
                    _auth_notice("success", "Session refreshed.")
                    st.rerun()
                _auth_notice("warning", "Please sign in again.")
            if st.button("Logout", key="settings_auth_logout", width="stretch"):
                logout_user()
                st.rerun()
            return

        _render_auth_tabs("settings")


def render_fullscreen_auth_gate() -> None:
    ensure_auth_state()
    _refresh_current_user_once()
    if st.session_state.get("auth_user"):
        return
    if not _claim_auth_panel_location("fullscreen"):
        return

    st.markdown(
        """
        <div class="auth-fullscreen-root" aria-hidden="true">
          <div class="auth-glow auth-glow-one"></div>
          <div class="auth-light-nodes">
            <span></span><span></span><span></span><span></span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="auth_fullscreen_panel"):
        _render_auth_tabs("fullscreen")


def is_authenticated() -> bool:
    ensure_auth_state()
    restore_browser_auth_session()
    _refresh_current_user_once()
    return bool(st.session_state.get("auth_user"))


def require_login(feature_name: str) -> bool:
    if is_authenticated():
        return True

    render_fullscreen_auth_gate()
    return False


def _render_current_user(user: dict, compact: bool = False) -> None:
    rows = [
        ("Email", user.get("email") or "-"),
        ("Name", user.get("full_name") or "-"),
        ("Role", user.get("role") or "user"),
        ("Status", "Active" if user.get("is_active", True) else "Inactive"),
    ]
    if compact:
        display_name = user.get("full_name") or user.get("email") or "Authenticated user"
        role = user.get("role") or "user"
        st.markdown(
            f"""
            <div class="auth-user-line">
              <span>{html.escape(str(display_name))}</span>
              <b>{html.escape(str(role))}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    for label, value in rows:
        st.markdown(
            f"""
            <div class="status-row">
              <span>{html.escape(label)}</span>
              <strong>{html.escape(str(value))}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_settings_account_summary(user: dict) -> None:
    rows = [
        ("Email", user.get("email") or "-"),
        ("Name", user.get("full_name") or "-"),
        ("Role", user.get("role") or "user"),
        ("Status", "Active" if user.get("is_active", True) else "Inactive"),
    ]
    if "is_email_verified" in user:
        rows.append(("Email verified", "Yes" if user.get("is_email_verified") else "No"))

    row_html = "".join(
        f"""
        <div class="auth-account-row">
          <span>{html.escape(label)}</span>
          <strong>{html.escape(str(value))}</strong>
        </div>
        """
        for label, value in rows
    )
    st.markdown(
        f"""
        <div class="auth-account-summary">
          {row_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_auth_tabs(location: str) -> None:
    if location != "fullscreen" and not _claim_auth_panel_location(location):
        return
    if _should_show_auth_notice():
        notice_kind = "error" if st.session_state.get("auth_notice_reason") == "login_failed" else "warning"
        _auth_notice(notice_kind, st.session_state.auth_error)

    options = ["Login", "Signup", "Reset", "Verify"]
    state_key = f"{location}_auth_tab_value"
    if state_key not in st.session_state:
        st.session_state[state_key] = "Login"

    with st.container(key=f"{location}_auth_tab_bar"):
        cols = st.columns(len(options), gap="small")
        for col, option in zip(cols, options):
            with col:
                is_active = st.session_state[state_key] == option
                if st.button(option.upper(), key=f"{location}_auth_tab_btn_{option.lower()}", type="primary" if is_active else "secondary", width="stretch"):
                    _clear_auth_action_feedback()
                    st.session_state[state_key] = option
                    st.rerun()

    selected = st.session_state[state_key]
    if selected == "Login":
        _render_login_form(location)
    elif selected == "Signup":
        _render_signup_form(location)
    elif selected == "Reset":
        _render_forgot_password_form(location)
    else:
        _render_verify_reset_forms(location)


def _should_show_auth_notice() -> bool:
    message = str(st.session_state.get("auth_error") or "").strip()
    if not message:
        return False
    if message == "Session expired. Please sign in again.":
        return st.session_state.get("auth_notice_reason") == "session_expired"
    return True


def _claim_auth_panel_location(location: str) -> bool:
    active_location = st.session_state.get("_auth_panel_active_location")
    if active_location and active_location != location:
        return False
    st.session_state["_auth_panel_active_location"] = location
    return True


def _current_page_url() -> str:
    context = getattr(st, "context", None)
    return str(getattr(context, "url", "") or "")


def _tab_switch(location: str, label: str, target: str, key_suffix: str) -> None:
    if st.button(label, key=f"{location}_auth_link_{key_suffix}", width="stretch"):
        _clear_auth_action_feedback()
        st.session_state[f"{location}_auth_tab_value"] = target
        st.rerun()


def _auth_mode_heading(title: str) -> None:
    st.markdown(f'<h2 class="auth-mode-heading">{html.escape(title)}</h2>', unsafe_allow_html=True)


def _reset_login_request_state() -> None:
    st.session_state["_login_in_progress"] = False
    st.session_state["_login_submit_consumed"] = False


def _clear_stale_login_attempt_state() -> None:
    st.session_state.auth_error = ""
    st.session_state.auth_notice_reason = ""
    _clear_auth_action_feedback()


def _clear_auth_action_feedback() -> None:
    st.session_state["_auth_action_feedback_mode"] = ""
    st.session_state["_auth_action_feedback_kind"] = ""
    st.session_state["_auth_action_feedback_message"] = ""


def _set_auth_action_feedback(mode: str, kind: str, message: str) -> None:
    st.session_state["_auth_action_feedback_mode"] = mode
    st.session_state["_auth_action_feedback_kind"] = kind
    st.session_state["_auth_action_feedback_message"] = message


def _render_auth_action_feedback(mode: str) -> None:
    if st.session_state.get("_auth_action_feedback_mode") != mode:
        return
    message = str(st.session_state.get("_auth_action_feedback_message") or "").strip()
    if message:
        _auth_notice(st.session_state.get("_auth_action_feedback_kind") or "info", message)


def _render_login_form(location: str) -> None:
    _auth_mode_heading("Welcome Back")
    button_disabled = bool(st.session_state.get("_login_in_progress", False))
    visibility_key = f"{location}_auth_login_password_visible"
    password_widget_key = f"{location}_auth_login_password"
    st.session_state.setdefault(visibility_key, False)
    if st.button(
        ":material/visibility_off:" if st.session_state[visibility_key] else ":material/visibility:",
        key=f"{location}_auth_login_password_visibility",
        help="Hide password" if st.session_state[visibility_key] else "Show password",
    ):
        st.session_state[visibility_key] = not st.session_state[visibility_key]
    with st.form(f"{location}_auth_login_form"):
        email = st.text_input("Email Address", key=f"{location}_auth_login_email", placeholder="Email Address")
        password = st.text_input(
            "Password",
            type="default" if st.session_state[visibility_key] else "password",
            key=password_widget_key,
            placeholder="Password",
        )
        submitted = st.form_submit_button(
            "LOGIN",
            type="primary",
            width="stretch",
            disabled=button_disabled,
        )

    link_cols = st.columns(2, gap="small")
    with link_cols[0]:
        _tab_switch(location, "Create account", "Signup", "login_signup")
    with link_cols[1]:
        _tab_switch(location, "Reset password", "Reset", "login_reset")

    if not submitted:
        return
    if st.session_state.get("_login_in_progress") or st.session_state.get("_login_submit_consumed"):
        return

    _clear_stale_login_attempt_state()
    st.session_state["_login_submit_consumed"] = True
    st.session_state["_login_in_progress"] = True
    navigation_attempted = False
    login_failed = False
    try:
        login_user(email, password)
        st.session_state.pop("_auth_panel_active_location", None)
        st.session_state.current_page = "Chat"
        st.session_state.active_main_tab = "Chat"
        navigation_attempted = True
        if hasattr(st, "switch_page"):
            st.switch_page("pages/chat.py")
            return
        st.rerun()
    except ApiClientError as exc:
        st.session_state.auth_error = (
            "Invalid email or password."
            if exc.status_code == 401
            else _clean_auth_message(str(exc))
        )
        st.session_state.auth_notice_reason = "login_failed"
        login_failed = True
    except Exception:
        raise
    finally:
        _reset_login_request_state()
    if login_failed:
        st.rerun()


def _render_signup_form(location: str) -> None:
    _auth_mode_heading("Create Account")
    with st.form(f"{location}_auth_signup_form"):
        full_name = st.text_input("Full Name", key=f"{location}_auth_signup_name", placeholder="Full Name")
        email = st.text_input("Email Address", key=f"{location}_auth_signup_email", placeholder="Email Address")
        password = st.text_input("Password", type="password", key=f"{location}_auth_signup_password", placeholder="Password")
        submitted = st.form_submit_button("CREATE ACCOUNT", type="primary", width="stretch")

    _tab_switch(location, "Already have account? Login", "Login", "signup_login")

    if not submitted:
        return
    try:
        result = signup_user(email, password, full_name)
        st.session_state.auth_error = ""
        _auth_notice(
            "success",
            "Account created. Check your email for verification link.",
            "If email is not received, check spam or SMTP configuration.",
        )
        verification_hint = result.get("verification_hint")
        if verification_hint:
            _render_dev_link("Development verification link", str(verification_hint))
        st.session_state[f"{location}_auth_tab_value"] = "Login"
    except ApiClientError as exc:
        st.session_state.auth_error = _clean_auth_message(str(exc))
        _auth_notice("error", st.session_state.auth_error)


def _render_forgot_password_form(location: str) -> None:
    _auth_mode_heading("Reset Password")
    _render_auth_action_feedback("forgot")
    with st.form(f"{location}_auth_forgot_form"):
        email = st.text_input("Email Address", key=f"{location}_auth_forgot_email", placeholder="Email Address")
        submitted = st.form_submit_button("SEND CODE", type="primary", width="stretch")

    _tab_switch(location, "Back to Login", "Login", "reset_login")

    if not submitted:
        return
    try:
        with st.spinner("Sending password reset instructions..."):
            result = forgot_password(email)
        st.session_state.auth_error = ""
        message = result.get("message") or "Password reset instructions sent if the email exists."
        _set_auth_action_feedback("forgot", "success", message)
        _auth_notice("success", message, "If email is not received, check spam or SMTP configuration.")
        reset_link = result.get("reset_link")
        if reset_link:
            _render_dev_link("Development reset link", str(reset_link))
    except ApiClientError as exc:
        message = _clean_auth_message(str(exc))
        _set_auth_action_feedback("forgot", "error", message)
        _auth_notice("error", message)


def _render_verify_reset_forms(location: str) -> None:
    _auth_mode_heading("Verify Account")
    _render_auth_action_feedback("verify")
    with st.form(f"{location}_auth_verify_email_form"):
        verify_token = st.text_input(
            "Verification Token",
            key=f"{location}_auth_verify_token",
            placeholder="Verification Token",
        )
        verify_submitted = st.form_submit_button("VERIFY EMAIL", type="primary", width="stretch")

    if verify_submitted:
        try:
            with st.spinner("Verifying email..."):
                result = verify_email(verify_token)
            st.session_state.auth_error = ""
            message = result.get("message") or "Email verified successfully. Please login."
            _set_auth_action_feedback("verify", "success", message)
            _auth_notice("success", message)
            st.session_state[f"{location}_auth_tab_value"] = "Login"
        except ApiClientError as exc:
            message = _clean_auth_message(str(exc))
            _set_auth_action_feedback("verify", "error", message)
            _auth_notice("error", message)

    st.caption("Have a password reset token? Set a new password below.")
    with st.form(f"{location}_auth_reset_form"):
        reset_token = st.text_input("Reset Token", key=f"{location}_auth_reset_token", placeholder="Reset Token")
        new_password = st.text_input("New Password", type="password", key=f"{location}_auth_reset_password", placeholder="New Password")
        reset_submitted = st.form_submit_button("RESET PASSWORD", type="primary", width="stretch")

    _tab_switch(location, "Back to Login", "Login", "verify_login")

    if not reset_submitted:
        return
    try:
        with st.spinner("Resetting password..."):
            result = reset_password(reset_token, new_password)
        st.session_state.auth_error = ""
        message = result.get("message") or "Password reset successfully. Please sign in."
        _set_auth_action_feedback("verify", "success", message)
        _auth_notice("success", message)
        st.session_state[f"{location}_auth_tab_value"] = "Login"
    except ApiClientError as exc:
        message = _clean_auth_message(str(exc))
        _set_auth_action_feedback("verify", "error", message)
        _auth_notice("error", message)


def _refresh_current_user_once() -> None:
    token = st.session_state.get("auth_token", "")
    if not token:
        return
    if st.session_state.get("auth_checked_token") == token and st.session_state.get("auth_user"):
        return
    get_current_user()


def _clean_auth_message(message: str) -> str:
    cleaned = message.strip().strip('"')
    if not cleaned:
        return "Authentication failed. Please try again."
    return cleaned


def _auth_notice(kind: str, title: str, detail: str = "") -> None:
    safe_kind = kind if kind in {"success", "error", "info", "warning"} else "info"
    detail_html = (
        f"<span>{html.escape(detail)}</span>"
        if detail
        else ""
    )
    st.markdown(
        f"""
        <div class="auth-message auth-message-{safe_kind}">
          <strong>{html.escape(title)}</strong>
          {detail_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_dev_link(label: str, url: str) -> None:
    escaped_url = html.escape(url, quote=True)
    st.markdown(
        f"""
        <div class="auth-dev-link">
          <span>{html.escape(label)}</span>
          <a href="{escaped_url}" target="_self" rel="noreferrer">Open link</a>
          <code>{html.escape(url)}</code>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_login_return(location: str) -> None:
    if st.button("Back to Login", key=f"{location}_verify_back_to_login", type="primary", width="stretch"):
        _set_auth_tabs("Login")
        try:
            st.query_params.clear()
        except AttributeError:
            st.experimental_set_query_params()
        if location.startswith("verify_page") and hasattr(st, "switch_page"):
            try:
                st.switch_page("app.py")
            except Exception:
                pass
        st.rerun()


def _set_auth_tabs(target: str) -> None:
    for key in list(st.session_state.keys()):
        if str(key).endswith("_auth_tab_value"):
            st.session_state[key] = target
    for location in ("fullscreen", "settings", "sidebar"):
        st.session_state[f"{location}_auth_tab_value"] = target


def _query_param(name: str) -> str:
    try:
        value = st.query_params.get(name, "")
    except AttributeError:
        value = st.experimental_get_query_params().get(name, "")
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _auth_key(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "auth"
