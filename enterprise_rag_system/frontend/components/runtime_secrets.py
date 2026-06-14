from __future__ import annotations

import os
import html
from pathlib import Path
from typing import Dict
import requests
import streamlit as st


REQUIRED_KEYS = ("OPENAI_API_KEY", "TAVILY_API_KEY")
WORKSPACE_REQUIRED_KEYS = ("OPENAI_API_KEY",)
SERVER_KEY_FLAGS = {
    "OPENAI_API_KEY": "openai_configured",
    "TAVILY_API_KEY": "tavily_configured",
    "QDRANT_URL": "qdrant_configured",
    "QDRANT_API_KEY": "qdrant_api_key_configured",
}
SESSION_KEY_PREFIX = "runtime_secret_"
VALIDATION_KEY = "runtime_secret_validation"
RESET_MESSAGE_KEY = "runtime_secret_reset_message"
USE_OPENAI_KEY = "runtime_use_openai"
LLM_FALLBACK_WARNING_KEY = "llm_fallback_warning"
FORCE_LOCAL_STUB_KEY = "runtime_force_local_stub"


def init_runtime_secret_state() -> None:
    st.session_state.setdefault(VALIDATION_KEY, {"fingerprint": "", "ok": False, "errors": {}, "warnings": {}})
    for name in REQUIRED_KEYS:
        st.session_state.setdefault(f"{SESSION_KEY_PREFIX}{name}", "")
    st.session_state.setdefault(USE_OPENAI_KEY, production_mvp_active())
    st.session_state.setdefault(FORCE_LOCAL_STUB_KEY, False)


def get_secret_value(name: str) -> str:
    if name in REQUIRED_KEYS:
        return str(st.session_state.get(f"{SESSION_KEY_PREFIX}{name}", "")).strip()
    return _env_value(name)


def get_key_source(name: str) -> str:
    if str(st.session_state.get(f"{SESSION_KEY_PREFIX}{name}", "")).strip():
        return "session"
    if name in REQUIRED_KEYS and _server_key_configured(name):
        return ".env"
    if name not in REQUIRED_KEYS and _env_value(name):
        return ".env"
    return "missing"


def required_keys_status() -> Dict[str, dict]:
    return {
        name: {
            "configured": bool(_server_key_configured(name) or get_secret_value(name)),
            "source": get_key_source(name),
            "masked": "Configured on server" if _server_key_configured(name) else mask_secret(get_secret_value(name)),
        }
        for name in REQUIRED_KEYS
    }


def has_required_keys() -> bool:
    if server_api_configured():
        return True
    status = required_keys_status()
    return all(status[name]["configured"] for name in _workspace_required_keys())


def local_test_mode_active() -> bool:
    state = st.session_state.get("server_api_config") or {}
    provider = str(state.get("effective_llm_provider") or state.get("llm_provider") or _env_value("LLM_PROVIDER") or "auto").lower()
    return bool(provider == "local_stub" or (not state and _env_truthy("LOCAL_TEST_MODE")))


def _workspace_required_keys() -> tuple[str, ...]:
    if local_test_mode_active():
        return ()
    return WORKSPACE_REQUIRED_KEYS


def production_mvp_active() -> bool:
    environment = _env_value("ENVIRONMENT").strip().lower()
    backend_url = _env_value("RAG_API_BASE_URL").strip().lower()
    return (
        _env_truthy("RENDER_FREE_MVP")
        or environment in {"production", "prod"}
        or ".onrender.com" in backend_url
    )


def default_embedding_provider() -> str:
    return "openai" if production_mvp_active() else "huggingface"


def server_api_configured(backend_health: dict | None = None) -> bool:
    state = _server_api_config_state(backend_health)
    return bool(state.get("configured"))


def tavily_available(backend_health: dict | None = None) -> bool:
    state = _server_api_config_state(backend_health)
    return bool(state.get("tavily_configured") or get_secret_value("TAVILY_API_KEY"))


def _server_api_config_state(backend_health: dict | None = None) -> dict:
    try:
        from services.api_client import cached_health

        health_payload = backend_health if backend_health and backend_health.get("success") else cached_health()
        st.session_state.backend_health = health_payload
    except Exception as exc:
        health_payload = backend_health or st.session_state.get("backend_health") or {}
        if not health_payload.get("success"):
            st.session_state.server_api_configured = False
            st.session_state.server_api_config_error = str(exc)
            return {"configured": False, "available": False, "error": str(exc)}

    local_test_mode = bool(health_payload.get("local_test_mode"))
    configured = bool(
        (health_payload.get("openai_configured") or local_test_mode)
        and health_payload.get("qdrant_configured")
        and health_payload.get("qdrant_api_key_configured")
    )
    state = {
        "configured": configured,
        "available": True,
        "openai_configured": bool(health_payload.get("openai_configured")),
        "llm_provider": str(health_payload.get("llm_provider") or "auto"),
        "effective_llm_provider": str(health_payload.get("effective_llm_provider") or "auto"),
        "llm_model": str(health_payload.get("llm_model") or "unknown"),
        "local_test_mode": local_test_mode,
        "runtime_openai_active": bool(health_payload.get("runtime_openai_active")),
        "qdrant_configured": bool(health_payload.get("qdrant_configured")),
        "qdrant_api_key_configured": bool(health_payload.get("qdrant_api_key_configured")),
        "tavily_configured": bool(health_payload.get("tavily_configured")),
    }
    st.session_state.server_api_configured = configured
    st.session_state.server_api_config = state
    st.session_state.server_api_config_error = ""
    return state


def _server_key_configured(name: str) -> bool:
    flag = SERVER_KEY_FLAGS.get(name)
    if not flag:
        return False
    state = st.session_state.get("server_api_config") or {}
    return bool(state.get(flag))


def require_runtime_credentials(location: str = "workspace") -> bool:
    init_runtime_secret_state()
    if has_required_keys():
        return True
    server_state = _server_api_config_state()
    if not server_state.get("available", True):
        render_backend_unavailable_gate(server_state.get("error", "Backend is not reachable."))
        st.stop()
    render_runtime_credential_gate(location)
    st.stop()
    return False


def render_backend_unavailable_gate(message: str) -> None:
    st.markdown(
        f"""
        <style>
          [data-testid="stSidebar"] {{ display: none !important; }}
          .block-container:has(.runtime-gate-root) {{
            max-width: 720px !important;
            padding-top: 1.2rem !important;
          }}
          .runtime-gate-shell {{
            background:#fff;
            border:1px solid #fecaca;
            border-radius:12px;
            box-shadow:0 14px 34px rgba(15,27,61,0.08);
            padding:0.9rem 1rem;
          }}
          .runtime-gate-shell h1 {{
            color:#991b1b;
            font-size:1.12rem;
            margin:0 0 0.25rem;
          }}
          .runtime-gate-shell p {{
            color:#7f1d1d;
            font-size:0.84rem;
            margin:0;
          }}
        </style>
        <span class="runtime-gate-root"></span>
        <div class="runtime-gate-shell">
          <h1>Backend unavailable</h1>
          <p>{html.escape(str(message))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_runtime_credential_gate(location: str = "workspace") -> None:
    st.markdown(
        """
        <style>
          [data-testid="stSidebar"] {
            display: none !important;
          }
          .block-container:has(.runtime-gate-root) {
            max-width: 720px !important;
            padding-top: 0.55rem !important;
            padding-bottom: 0.4rem !important;
          }
          .runtime-gate-shell {
            background: #ffffff;
            border: 1px solid rgba(203,213,225,0.9);
            border-radius: 12px;
            box-shadow: 0 14px 34px rgba(15,27,61,0.08);
            padding: 0.82rem 0.9rem 0.7rem;
          }
          .runtime-gate-header {
            margin-bottom: 0.48rem;
          }
          .runtime-gate-header span {
            color: #4f46e5;
            font-size: 0.7rem;
            font-weight: 850;
            letter-spacing: 0.04em;
            text-transform: uppercase;
          }
          .runtime-gate-header h1 {
            color: #0f1b3d;
            font-size: 1.12rem;
            line-height: 1.2;
            margin: 0.08rem 0 0.12rem;
          }
          .runtime-gate-header p {
            color: #60708f;
            font-size: 0.8rem;
            line-height: 1.28;
            margin: 0;
          }
          .runtime-gate-note {
            align-items: flex-start;
            background: rgba(59,130,246,0.07);
            border: 1px solid rgba(59,130,246,0.18);
            border-radius: 10px;
            color: #0f172a;
            display: flex;
            gap: 0.55rem;
            margin-bottom: 0.5rem;
            padding: 0.52rem 0.62rem;
          }
          .runtime-gate-note-icon {
            font-size: 0.95rem;
            line-height: 1.2;
          }
          .runtime-gate-note strong {
            display: block;
            font-size: 0.8rem;
            margin-bottom: 0.08rem;
          }
          .runtime-gate-note p {
            color: #475569;
            font-size: 0.74rem;
            line-height: 1.26;
            margin: 0;
          }
          .runtime-gate-shell div[data-testid="stTextInput"] {
            margin-bottom: 0 !important;
          }
          .runtime-gate-shell div[data-testid="stTextInput"] label p {
            font-size: 0.72rem !important;
            font-weight: 760 !important;
          }
          .runtime-gate-shell div[data-testid="stTextInput"] input {
            min-height: 34px !important;
            font-size: 0.8rem !important;
          }
          .runtime-gate-shell div[data-testid="stForm"] {
            border: 0 !important;
            padding: 0 !important;
          }
          .runtime-env-row {
            align-items: center;
            background: rgba(15, 23, 42, 0.04);
            border: 1px solid rgba(203, 213, 225, 0.78);
            border-radius: 9px;
            display: flex;
            justify-content: space-between;
            min-height: 34px;
            padding: 0.38rem 0.55rem;
          }
          .runtime-env-row span {
            color: #334155;
            font-size: 0.72rem;
            font-weight: 760;
          }
          .runtime-env-row strong {
            color: #047857;
            font-size: 0.68rem;
            font-weight: 800;
            white-space: nowrap;
          }
          .runtime-gate-shell [data-testid="stVerticalBlock"] {
            gap: 0.28rem !important;
          }
          .runtime-gate-shell [data-testid="stHorizontalBlock"] {
            gap: 0.55rem !important;
          }
          .runtime-gate-shell .stButton > button,
          .runtime-gate-shell [data-testid="stFormSubmitButton"] button {
            min-height: 36px !important;
            padding: 0.38rem 0.7rem !important;
          }
          .runtime-gate-footer {
            display: flex;
            justify-content: flex-end;
            margin-top: 0.22rem;
          }
          .runtime-mode-chip {
            background: #ecfdf5;
            border: 1px solid #a7f3d0;
            border-radius: 999px;
            color: #047857;
            display: inline-flex;
            font-size: 0.72rem;
            font-weight: 800;
            margin: 0 0 0.5rem;
            padding: 0.22rem 0.55rem;
          }
        </style>
        <span class="runtime-gate-root"></span>
        <div class="runtime-gate-shell">
          <div class="runtime-gate-header">
            <span>Secure runtime access</span>
            <h1>API setup required</h1>
            <p>Add API credentials to continue. They are used for backend requests in this Streamlit session only.</p>
          </div>
          <div class="runtime-gate-note">
            <div class="runtime-gate-note-icon">🔐</div>
            <div>
              <strong>Runtime-only credentials</strong>
              <p>Your keys are sent to the backend only with the current request. This app does not save them to the database, .env, browser storage, URL, or logs.</p>
            </div>
          </div>
        """,
        unsafe_allow_html=True,
    )
    if local_test_mode_active():
        st.markdown(
            '<span class="runtime-mode-chip">Local test mode active &mdash; OpenAI optional</span>',
            unsafe_allow_html=True,
        )
    _render_runtime_key_form(f"runtime_gate_{location}")
    st.markdown('<div class="runtime-gate-footer">', unsafe_allow_html=True)
    if st.button("Logout", key=f"runtime_gate_logout_{location}"):
        from services.api_client import logout_user

        logout_user()
        st.rerun()
    st.markdown("</div></div>", unsafe_allow_html=True)


def _render_runtime_key_form(location: str) -> bool:
    with st.form(f"runtime_api_key_setup_{location}"):
        st.checkbox("Use OpenAI for this session", key=USE_OPENAI_KEY)
        st.caption("Optional. Add your OpenAI key for better answers. Leave empty to use local test mode.")
        cols = st.columns(2)
        with cols[0]:
            _runtime_text_input(
                "OPENAI_API_KEY",
                "OpenAI API key",
                "Optional in local test mode",
                password=True,
                optional=local_test_mode_active(),
            )
        with cols[1]:
            _runtime_text_input("TAVILY_API_KEY", "Tavily API key", "tvly-...", password=True, optional=True)
        submitted = st.form_submit_button("Validate & Continue", type="primary", width="stretch")

    if submitted:
        values = _candidate_values()
        ok, errors = validate_runtime_keys(values)
        if ok:
            for name in REQUIRED_KEYS:
                st.session_state[f"{SESSION_KEY_PREFIX}{name}"] = values[name].strip()
            if st.session_state.get(USE_OPENAI_KEY):
                st.session_state[FORCE_LOCAL_STUB_KEY] = False
            st.success("API configuration validated for this session.")
            for name, message in st.session_state.get(VALIDATION_KEY, {}).get("warnings", {}).items():
                st.warning(f"{name}: {message}")
            st.rerun()
        for name, message in errors.items():
            st.error(f"{name}: {message}")

    cached_errors = st.session_state.get(VALIDATION_KEY, {}).get("errors", {})
    if cached_errors and not submitted:
        for name, message in cached_errors.items():
            st.warning(f"{name}: {message}")
    cached_warnings = st.session_state.get(VALIDATION_KEY, {}).get("warnings", {})
    if cached_warnings and not submitted:
        for name, message in cached_warnings.items():
            st.warning(f"{name}: {message}")
    return False


def _runtime_text_input(
    name: str,
    label: str,
    placeholder: str,
    password: bool = False,
    optional: bool = False,
) -> None:
    if _server_key_configured(name) and name != "OPENAI_API_KEY":
        st.markdown(
            f"""
            <div class="runtime-env-row">
              <span>{html.escape(label)}</span>
              <strong>Configured on server</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
    suffix = " (optional)" if optional else ""
    st.text_input(
        f"{label}{suffix}",
        type="password" if password else "default",
        key=f"setup_input_{name}",
        placeholder=placeholder,
        help="Stored only in Streamlit session and sent per request.",
    )
    if name == "OPENAI_API_KEY":
        st.caption("Optional. Add your OpenAI key for better answers. Leave empty to use local test mode.")


def clear_runtime_key_state() -> None:
    for name in REQUIRED_KEYS:
        st.session_state.pop(name, None)
        st.session_state.pop(f"{SESSION_KEY_PREFIX}{name}", None)
        st.session_state.pop(f"{name}_source", None)
        st.session_state.pop(f"setup_input_{name}", None)
    st.session_state.pop(VALIDATION_KEY, None)
    st.session_state.pop("runtime_keys_validated", None)
    st.session_state.pop("runtime_key_validation_errors", None)
    st.session_state.pop(USE_OPENAI_KEY, None)
    st.session_state.pop(LLM_FALLBACK_WARNING_KEY, None)
    st.session_state.pop(FORCE_LOCAL_STUB_KEY, None)


def reset_session_keys() -> None:
    clear_runtime_key_state()
    st.session_state[RESET_MESSAGE_KEY] = "Session API keys cleared. Please enter keys again if .env is missing."


def maybe_request_key_reset(label: str = "Reset session keys") -> bool:
    if st.button(label, width="stretch"):
        reset_session_keys()
        st.rerun()
    return False


def mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "Missing"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def validation_is_current() -> bool:
    cached = st.session_state.get(VALIDATION_KEY, {})
    return bool(cached.get("ok")) and cached.get("fingerprint") == _fingerprint(_candidate_values())


def validate_runtime_keys(values: dict[str, str] | None = None) -> tuple[bool, dict[str, str]]:
    values = values or _candidate_values()
    errors: dict[str, str] = {}
    warnings: dict[str, str] = {}

    for name in _workspace_required_keys():
        if _server_key_configured(name):
            continue
        if not values.get(name, "").strip():
            errors[name] = "Required."

    openai_key = values.get("OPENAI_API_KEY", "").strip()
    if st.session_state.get(USE_OPENAI_KEY) and not (_server_key_configured("OPENAI_API_KEY") or openai_key):
        errors["OPENAI_API_KEY"] = "Add an OpenAI API key or turn off OpenAI for this session."
    if openai_key and not (openai_key.startswith("sk-") or openai_key.startswith("sess-")):
        errors["OPENAI_API_KEY"] = "Use a valid OpenAI API key format."
    if st.session_state.get(USE_OPENAI_KEY) and openai_key and "OPENAI_API_KEY" not in errors:
        openai_error = _validate_openai_key(openai_key)
        if openai_error:
            errors["OPENAI_API_KEY"] = openai_error

    tavily_key = values.get("TAVILY_API_KEY", "").strip()
    if tavily_key and len(tavily_key) < 12:
        errors["TAVILY_API_KEY"] = "Use a valid Tavily API key."

    ok = not errors
    st.session_state[VALIDATION_KEY] = {
        "fingerprint": _fingerprint(values),
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
    }
    return ok, errors


def render_api_key_setup_panel(location: str = "main") -> bool:
    init_runtime_secret_state()
    if has_required_keys() and validation_is_current():
        return True

    status = required_keys_status()
    missing = [name for name, item in status.items() if not item["configured"]]
    title = "API setup required" if missing else "Validate API configuration"
    details = "API keys are missing. Add them in .env or enter them below to continue."

    reset_message = st.session_state.pop(RESET_MESSAGE_KEY, "")
    if reset_message:
        st.info(reset_message)

    st.markdown(
        f"""
        <div class="api-setup-panel">
          <div class="api-setup-header">
            <div>
              <h3>{title}</h3>
              <p>{details}</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="security-info-card">
          <div class="security-info-icon">🔐</div>
          <div>
            <strong>Runtime-only credentials</strong>
            <p>Your API keys are not stored in our database or .env file. They are sent securely per request and used only for the current operation.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form(f"runtime_api_key_setup_{location}"):
        st.checkbox("Use OpenAI for this session", key=USE_OPENAI_KEY)
        st.caption("Optional. Add your OpenAI key for better answers. Leave empty to use local test mode.")
        cols = st.columns(2)
        with cols[0]:
            st.text_input(
                "OPENAI_API_KEY (Optional in local test mode)" if local_test_mode_active() else "OPENAI_API_KEY",
                type="password",
                key="setup_input_OPENAI_API_KEY",
                placeholder="sk-...",
                disabled=False,
                help="Optional in local test mode. Used for OpenAI chat generation and OpenAI embeddings when configured.",
            )
            st.caption("Optional. Add your OpenAI key for better answers. Leave empty to use local test mode.")
        with cols[1]:
            st.text_input(
                "TAVILY_API_KEY (optional)",
                type="password",
                key="setup_input_TAVILY_API_KEY",
                placeholder="tvly-...",
                help="Optional. Enables web fallback search when configured.",
            )
        submitted = st.form_submit_button("Validate & Continue", type="primary", width="stretch")

    if submitted:
        values = _candidate_values()
        ok, errors = validate_runtime_keys(values)
        if ok:
            for name in REQUIRED_KEYS:
                st.session_state[f"{SESSION_KEY_PREFIX}{name}"] = values[name].strip()
            if st.session_state.get(USE_OPENAI_KEY):
                st.session_state[FORCE_LOCAL_STUB_KEY] = False
            st.success("API configuration validated for this session.")
            for name, message in st.session_state.get(VALIDATION_KEY, {}).get("warnings", {}).items():
                st.warning(f"{name}: {message}")
            st.rerun()
        for name, message in errors.items():
            st.error(f"{name}: {message}")

    cached_errors = st.session_state.get(VALIDATION_KEY, {}).get("errors", {})
    if cached_errors and not submitted:
        for name, message in cached_errors.items():
            st.warning(f"{name}: {message}")
    cached_warnings = st.session_state.get(VALIDATION_KEY, {}).get("warnings", {})
    if cached_warnings and not submitted:
        for name, message in cached_warnings.items():
            st.warning(f"{name}: {message}")
    return False


def render_compact_api_status() -> None:
    status = required_keys_status()
    server_state = _server_api_config_state()
    llm_provider = str(server_state.get("effective_llm_provider") or server_state.get("llm_provider") or "unknown")
    llm_model = str(server_state.get("llm_model") or "unknown")
    use_openai = bool(st.session_state.get(USE_OPENAI_KEY))
    runtime_openai_key = bool(get_secret_value("OPENAI_API_KEY"))
    fallback_warning = str(st.session_state.get(LLM_FALLBACK_WARNING_KEY) or "") if use_openai else ""
    if local_test_mode_active():
        st.markdown(
            '<div class="runtime-mode-chip">Local test mode active &mdash; OpenAI optional</div>',
            unsafe_allow_html=True,
        )
    groups = {
        "OpenAI": status["OPENAI_API_KEY"],
        "Tavily": status["TAVILY_API_KEY"],
        "Qdrant": {
            "configured": bool(server_state.get("qdrant_configured")),
            "source": "backend" if server_state.get("qdrant_configured") else "missing",
            "masked": "Configured on backend" if server_state.get("qdrant_configured") else "Missing",
        },
    }
    st.markdown('<div class="sidebar-status-card"><strong>API Status</strong>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="api-status-row">
          <span>Current LLM</span>
          <b>{html.escape(llm_provider)}</b>
        </div>
        <div class="api-status-row">
          <span>Model</span>
          <b>{html.escape(llm_model)}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for label, item in groups.items():
        optional_local_openai = label == "OpenAI" and local_test_mode_active()
        runtime_openai_active = label == "OpenAI" and use_openai and runtime_openai_key
        if label == "OpenAI" and runtime_openai_active:
            state = "Runtime key active"
            css = "api-ok"
        elif label == "OpenAI" and not use_openai:
            server_default_openai = bool(server_state.get("openai_configured")) and llm_provider.lower() == "openai"
            state = "Server default" if server_default_openai else ("Inactive" if optional_local_openai else "Disabled")
            css = "api-ok" if server_default_openai or optional_local_openai else "api-missing"
        else:
            state = "Optional" if optional_local_openai else ("Connected" if item["configured"] else "Missing")
            css = "api-ok" if item["configured"] or optional_local_openai else "api-missing"
        st.markdown(
            f"""
            <div class="api-status-row">
              <span><i class="api-dot {css}"></i>{label}</span>
              <b>{state}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    if fallback_warning:
        st.warning(fallback_warning)


def render_openai_session_controls() -> None:
    st.toggle("Use OpenAI for this session", key=USE_OPENAI_KEY)
    if st.session_state.get(USE_OPENAI_KEY):
        st.text_input(
            "OpenAI runtime key",
            type="password",
            key="sidebar_runtime_openai_input",
            placeholder="sk-...",
            help="Optional. Add your OpenAI key for better answers. Leave empty to use local test mode.",
        )
        if st.button("Activate runtime key", key="sidebar_activate_openai", width="stretch"):
            key = str(st.session_state.get("sidebar_runtime_openai_input") or "").strip()
            if not (key.startswith("sk-") or key.startswith("sess-")):
                st.error("Use a valid OpenAI API key format.")
            else:
                error = _validate_openai_key(key)
                if error:
                    st.error(error)
                else:
                    st.session_state[f"{SESSION_KEY_PREFIX}OPENAI_API_KEY"] = key
                    st.session_state.pop(LLM_FALLBACK_WARNING_KEY, None)
                    st.session_state[FORCE_LOCAL_STUB_KEY] = False
                    st.rerun()


def runtime_secret_payload() -> dict[str, str | bool]:
    use_openai = bool(st.session_state.get(USE_OPENAI_KEY))
    return {
        "openai_api_key": get_secret_value("OPENAI_API_KEY"),
        "tavily_api_key": get_secret_value("TAVILY_API_KEY"),
        "use_openai": use_openai,
        "force_local_stub": bool(st.session_state.get(FORCE_LOCAL_STUB_KEY)),
    }


def _candidate_values() -> dict[str, str]:
    values = {}
    for name in REQUIRED_KEYS:
        values[name] = str(st.session_state.get(f"setup_input_{name}", "")).strip() or str(
            st.session_state.get(f"{SESSION_KEY_PREFIX}{name}", "")
        ).strip()
    return values


def _fingerprint(values: dict[str, str]) -> str:
    return "|".join(f"{name}:{len(values.get(name, ''))}:{values.get(name, '')[-4:]}" for name in REQUIRED_KEYS)


def _env_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return _dotenv_values().get(name, "").strip()


def _env_truthy(name: str) -> bool:
    return _env_value(name).lower() in {"1", "true", "yes", "on"}


@st.cache_data(show_spinner=False)
def _dotenv_values() -> dict[str, str]:
    roots = [
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[2] / "backend" / ".env",
    ]
    values: dict[str, str] = {}
    for path in roots:
        if not path.exists():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        except OSError:
            continue
    return values


def _validate_openai_key(api_key: str) -> str:
    try:
        response = requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=(5, 20),
        )
    except requests.Timeout:
        return "OpenAI validation timed out. Try again or turn off OpenAI for this session."
    except requests.RequestException:
        return "Could not validate the OpenAI key. Try again or turn off OpenAI for this session."
    if response.status_code == 429:
        return "OpenAI rate limit or quota error. Leave OpenAI off to use local test mode."
    if response.status_code in {401, 403}:
        return "OpenAI rejected this API key."
    if not response.ok:
        return f"OpenAI validation failed with HTTP {response.status_code}."
    return ""


def _combined_source(first: str, second: str) -> str:
    sources = {get_key_source(first), get_key_source(second)}
    if sources == {".env"}:
        return ".env"
    if "missing" in sources:
        return "missing"
    if "session" in sources:
        return "session"
    return ".env"
