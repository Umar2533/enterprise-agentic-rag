from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from components.auth_panel import is_authenticated
from components.layout import init_session_state
from components.runtime_secrets import has_required_keys, render_compact_api_status, render_openai_session_controls
from services.api_client import logout_user


NAV_ITEMS = [
    ("Chat", "pages/chat.py", "Chat", "chat"),
    ("Collections", "pages/collections.py", "Collections", "library"),
    ("Upload", "pages/upload.py", "Upload", "upload"),
    ("Analytics", "pages/analytics.py", "Analytics", "chart"),
    ("Settings", "pages/settings.py", "Settings", "settings"),
]
VALID_PAGES = {match_name for _, _, match_name, _ in NAV_ITEMS}
NAV_ICONS = {
    "chat": ":material/chat_bubble:",
    "library": ":material/library_books:",
    "upload": ":material/upload_file:",
    "chart": ":material/analytics:",
    "settings": ":material/settings:",
}


def render_sidebar(active_page: str = "Chat") -> dict:
    init_session_state()
    if not is_authenticated():
        return {"active_page": active_page, "backend_healthy": True}
    if not has_required_keys():
        return {"active_page": active_page, "backend_healthy": True}

    current_page = _resolve_current_page(active_page)
    health = st.session_state.get("backend_health", {})
    is_healthy = bool(health.get("success", True))

    sidebar_state = "collapsed" if st.session_state["sidebar_collapsed"] else "expanded"
    st.markdown(f'<span class="sidebar-state-marker sidebar-state-{sidebar_state}"></span>', unsafe_allow_html=True)
    _render_sidebar_toggle()
    _render_collapsed_icon_rail(current_page)
    with st.sidebar:
        st.markdown('<span class="ai-sidebar-scroll-anchor"></span>', unsafe_allow_html=True)
        with st.container(key="sidebar_scroll_content"):
            st.markdown(
                """
                <div class="ai-sidebar-brand">
                  <div class="ai-sidebar-logo">R</div>
                  <div>
                    <div class="ai-sidebar-title">Enterprise RAG</div>
                    <div class="ai-sidebar-subtitle"> AI workspace </div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown('<br>', unsafe_allow_html=True)
            _render_nav(current_page)

            _render_recent_activity()
            _render_active_workspace()
            st.markdown("""<br>""",unsafe_allow_html=True,)
            with st.expander("API Status", expanded=False):
                # st.markdown('<span class="sidebar-api-status-anchor"></span>', unsafe_allow_html=True)
                render_compact_api_status()
                st.markdown("""<br>""",unsafe_allow_html=True,)
                render_openai_session_controls()
                st.markdown("""<br>""",unsafe_allow_html=True,)
        with st.container(key="sidebar_account_footer"):
            _render_account_profile()
        

    return {"active_page": current_page, "backend_healthy": is_healthy}


def _resolve_current_page(active_page: str) -> str:
    requested = str(active_page or "").strip()
    if requested in VALID_PAGES:
        st.session_state.current_page = requested
        st.session_state.active_main_tab = requested
        return requested

    st.session_state.current_page = "Chat"
    st.session_state.active_main_tab = "Chat"
    return "Chat"


def _render_nav(active_page: str) -> None:
    st.markdown('<div class="ai-sidebar-section">Workspace</div>', unsafe_allow_html=True)
    st.markdown('<br>', unsafe_allow_html=True)
    for title, target, _, icon in NAV_ITEMS:
        st.page_link(target, label=title, icon=NAV_ICONS[icon], width="stretch")


def _navigate_to_page(page_name: str, target: str | None) -> None:
    st.session_state.current_page = page_name
    st.session_state.active_main_tab = page_name
    if target and hasattr(st, "switch_page") and _target_exists(target):
        st.switch_page(target)
    st.rerun()


def _render_active_workspace() -> None:
    active_collection = _active_collection_label()
    full_collection = active_collection if active_collection != "No active collection" else ""
    retrieval_mode = st.session_state.get("retrieval_mode") or "unknown"
    state_class = "is-active" if active_collection != "No active collection" else "is-idle"
    st.markdown(
        f"""
        <div class="ai-workspace {state_class}" title="{html.escape(full_collection, quote=True)}">
          <div>
            <span>Collection</span>
            <strong>{html.escape(_truncate(active_collection, 24))}</strong>
          </div>
          <small>{html.escape(_truncate(str(retrieval_mode), 26))}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_recent_activity() -> None:
    logs = _active_collection_logs()
    st.markdown("""<br>""",unsafe_allow_html=True,)
    with st.expander("Recents", expanded=bool(logs)):
        if not logs:
            st.caption("No recent chats for this collection.")
        else:
            for index, log in enumerate(reversed(logs[-8:])):
                log_id = log.get("id") or f"missing_{index}"
                title = _summarize_log_title(log)
                button_type = "primary" if log_id == st.session_state.get("active_query_log_id") else "secondary"
                if st.button(f"- {title}", key=f"sidebar_log_{log_id}_{index}", width="stretch", type=button_type):
                    st.session_state.active_query_log_id = log_id
                    st.session_state.active_main_tab = "Chat"
                    st.session_state.current_page = "Chat"
                    st.session_state.chat_export_pdf = None
                    st.rerun()

        if logs and st.button("Clear", key="sidebar_clear_query_logs", width="stretch"):
            active_keys = _active_collection_keys()
            st.session_state.query_logs = [
                log for log in st.session_state.get("query_logs", [])
                if _log_collection_key(log) not in active_keys
            ]
            st.session_state.active_query_log_id = ""
            st.session_state.chat_export_pdf = None
            st.rerun()


def _render_account_profile() -> None:
    user = st.session_state.get("auth_user") or {}
    display = user.get("full_name") or user.get("email") or "User"
    email = user.get("email") or ""
    role = user.get("role") or "user"
    initials = _initials(display)
    st.markdown(
        f"""
        <div class="ai-account" title="{html.escape(email or display, quote=True)}">
          <div class="ai-account-avatar">{html.escape(initials)}</div>
          <div class="ai-account-main">
            <strong>{html.escape(_truncate(str(display), 22))}</strong>
            <span>{html.escape(_truncate(email or role, 26))}</span>
          </div>
          <em>{html.escape(str(role))}</em>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button(_logout_icon_label(), key="sidebar_auth_logout", width="stretch", help="Logout"):
        _request_logout()
    _render_logout_confirmation()

def _render_collapsed_icon_rail(active_page: str) -> None:
    with st.container(key="notebook_collapsed_controls"):
        for title, target, match_name, icon in NAV_ITEMS:
            button_type = "primary" if active_page.lower() == match_name.lower() else "secondary"
            if st.button(_rail_icon_label(icon), key=f"collapsed_nav_{match_name}", help=title, type=button_type):
                _navigate_to_page(match_name, target)
        if st.button(_logout_icon_label(), key="collapsed_sidebar_logout", help="Logout"):
            _request_logout()
        _render_logout_confirmation(compact=True)


def _render_sidebar_toggle() -> None:
    collapsed = st.session_state["sidebar_collapsed"]
    with st.container(key="sidebar_toggle_controls"):
        st.button(
            ">>" if collapsed else "<<",
            key="sidebar_global_toggle",
            help="Expand sidebar" if collapsed else "Collapse sidebar",
            on_click=_toggle_sidebar,
        )


def _toggle_sidebar() -> None:
    st.session_state["sidebar_collapsed"] = not st.session_state.get("sidebar_collapsed", False)


def _request_logout() -> None:
    st.session_state.sidebar_logout_pending = True
    st.rerun()


def _render_logout_confirmation(compact: bool = False) -> None:
    if not st.session_state.get("sidebar_logout_pending"):
        return
    with st.container(key="sidebar_logout_confirm_compact" if compact else "sidebar_logout_confirm"):
        st.caption("Logout?")
        if compact:
            if st.button("Log out", key="sidebar_logout_confirm_ok_compact"):
                st.session_state.sidebar_logout_pending = False
                logout_user()
                st.rerun()
            if st.button("Cancel", key="sidebar_logout_confirm_cancel_compact"):
                st.session_state.sidebar_logout_pending = False
                st.rerun()
            return

        col_ok, col_cancel = st.columns(2)
        with col_ok:
            if st.button("OK", key="sidebar_logout_confirm_ok"):
                st.session_state.sidebar_logout_pending = False
                logout_user()
                st.rerun()
        with col_cancel:
            if st.button("Cancel", key="sidebar_logout_confirm_cancel"):
                st.session_state.sidebar_logout_pending = False
                st.rerun()

def _active_collection_label() -> str:
    raw = (
        st.session_state.get("active_collection_display_name")
        or st.session_state.get("active_collection")
        or st.session_state.get("selected_collection_display_name")
        or st.session_state.get("collection_name")
        or ""
    )
    friendly = _friendly_collection_name(str(raw))
    return friendly or "No active collection"


def _friendly_collection_name(value: str) -> str:
    name = (value or "").strip()
    if not name:
        return ""
    for prefix in ("agentic_rag_enterprise_", "agentic_rag_enterprise"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return " ".join(part for part in name.replace("-", " ").replace("_", " ").split() if part).title() or value


def _active_collection_keys() -> set[str]:
    keys = {
        st.session_state.get("active_collection"),
        st.session_state.get("active_collection_display_name"),
        st.session_state.get("active_collection_name"),
        st.session_state.get("collection_name"),
        st.session_state.get("selected_collection"),
        st.session_state.get("attached_collection"),
    }
    keys = {str(key).strip() for key in keys if str(key or "").strip()}
    keys.update({_friendly_collection_name(key) for key in list(keys)})
    return {key for key in keys if key}


def _log_collection_key(log: dict) -> str:
    return str(
        log.get("collection_name")
        or log.get("collection")
        or log.get("active_collection")
        or ""
    ).strip()


def _active_collection_logs() -> list[dict]:
    active_keys = _active_collection_keys()
    if not active_keys:
        return []
    return [
        log for log in st.session_state.get("query_logs", [])
        if _log_collection_key(log) in active_keys
        or _friendly_collection_name(_log_collection_key(log)) in active_keys
    ]


def _summarize_log_title(log: dict) -> str:
    title = str(log.get("title") or "").strip()
    if not title:
        for message in log.get("messages", []):
            if message.get("role") == "user":
                title = str(message.get("content") or "")
                break
    title = " ".join(title.replace("\n", " ").split()) or "Untitled chat"
    return _truncate(title, 54)


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _initials(value: str) -> str:
    parts = [part for part in str(value or "U").replace("@", " ").replace(".", " ").split() if part]
    return "".join(part[0].upper() for part in parts[:2]) or "U"


def _page_href(target: str | None) -> str:
    if not target:
        return "#"
    stem = Path(target).stem.replace("_", "-")
    return stem


def _icon_svg(name: str) -> str:
    safe_name = name if name in {"chat", "library", "upload", "chart", "settings"} else "chat"
    return f'<span class="sidebar-glyph sidebar-glyph-{safe_name}" aria-hidden="true"></span>'


def _rail_icon_label(name: str) -> str:
    labels = {
        "chat": chr(0x25D4),
        "library": chr(0x25A3),
        "upload": "+",
        "chart": chr(0x2301),
        "settings": chr(0x2261),
    }
    return labels.get(name, chr(0x25D4))


def _logout_icon_label() -> str:
    return chr(0x21AA)


def _target_exists(target: str) -> bool:
    frontend_root = Path(__file__).resolve().parents[1]
    return (frontend_root / target).exists()
