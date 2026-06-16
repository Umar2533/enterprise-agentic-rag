import html

import streamlit as st

from components.auth_panel import is_authenticated, render_fullscreen_auth_gate
from components.layout import init_session_state, load_styles, validate_build_settings
from components.runtime_secrets import (
    LLM_FALLBACK_WARNING_KEY,
    OPENAI_QUOTA_MESSAGE,
    get_key_source,
    has_required_keys,
    maybe_request_key_reset,
    render_api_key_setup_panel,
    require_runtime_credentials,
    required_keys_status,
)
from components.sidebar import render_sidebar
from services.api_client import API_BASE_URL, ApiClientError, cached_health


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


# def _load_health() -> dict:
#     try:
#         st.session_state.backend_health = health()
#     except ApiClientError as exc:
#         st.session_state.backend_health = {"success": False, "error": str(exc)}
#     return st.session_state.backend_health


# def _status_badge(label: str, ok: bool) -> None:
#     css = "status-active" if ok else "status-error"
#     st.markdown(f'<span class="status-badge {css}">{label}</span>', unsafe_allow_html=True)


# def _render_embedding_settings() -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>Embedding Settings</h3><p>Used by upload/build and collection attach flows.</p></div></div>', unsafe_allow_html=True)
#         st.selectbox("Embedding provider", ["huggingface", "openai"], key="embedding_provider")


# def _render_llm_settings() -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>LLM Provider Settings</h3><p>OpenAI is the configured generation provider.</p></div></div>', unsafe_allow_html=True)
#         _status_badge("OpenAI configured" if get_key_source("OPENAI_API_KEY") != "missing" else "OpenAI missing", get_key_source("OPENAI_API_KEY") != "missing")


# def _render_chunking_settings() -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>Chunking Settings</h3><p>Controls how uploaded documents are split.</p></div></div>', unsafe_allow_html=True)
#         st.slider("Chunk size", 300, 1500, key="chunk_size", step=50)
#         st.slider("Chunk overlap", 0, 300, key="chunk_overlap", step=10)


# def _render_retrieval_settings() -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>Retrieval Settings</h3><p>Hybrid retrieval and answer quality controls.</p></div></div>', unsafe_allow_html=True)
#         col1, col2 = st.columns(2)
#         with col1:
#             st.slider("Top K", 1, 12, key="top_k")
#             st.checkbox("Enable grading", key="enable_grading")
#         with col2:
#             st.slider("Max iterations", 1, 5, key="max_iterations")
#             st.checkbox("Enable evaluation", key="enable_evaluation")


# def _render_api_configuration() -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>API Configuration</h3><p>Runtime keys resolve from .env first, then session.</p></div></div>', unsafe_allow_html=True)
#         st.text_input("FastAPI base URL", value=API_BASE_URL, disabled=True)
#         if has_required_keys():
#             st.markdown('<span class="status-badge status-active">API configured</span>', unsafe_allow_html=True)
#         else:
#             render_api_key_setup_panel("settings")


# def _render_key_sources() -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>Key Sources</h3><p>Secrets are masked and never displayed in full.</p></div></div>', unsafe_allow_html=True)
#         for name, item in required_keys_status().items():
#             source = item["source"]
#             badge = "ok" if source != "missing" else "warn"
#             st.markdown(
#                 f"""
#                 <div class="status-row">
#                   <span>{html.escape(name)}</span>
#                   <strong><span class="mini-chip {badge}">{source}</span> {html.escape(item["masked"])}</strong>
#                 </div>
#                 """,
#                 unsafe_allow_html=True,
#             )
#         maybe_request_key_reset()


# def _render_cache_settings() -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>Cache Settings</h3><p>Backend cache controls will appear here when available.</p></div></div>', unsafe_allow_html=True)
#         st.markdown('<div class="empty-state"><div><strong>No cache controls</strong><span>No configurable cache settings are available from backend.</span></div></div>', unsafe_allow_html=True)


# def _render_system_preferences(backend_health: dict) -> None:
#     with st.container(border=True):
#         st.markdown('<div class="section-title"><div><h3>System Preferences</h3><p>Current runtime and backend state.</p></div></div>', unsafe_allow_html=True)
#         rows = [
#             ("Backend", "Online" if backend_health.get("success") else "Offline"),
#             ("Vector DB", backend_health.get("vector_db_provider") or "-"),
#             ("OpenAI key source", get_key_source("OPENAI_API_KEY")),
#             ("Tavily key source", get_key_source("TAVILY_API_KEY")),
#             ("Qdrant URL source", get_key_source("QDRANT_URL")),
#             ("Qdrant API key source", get_key_source("QDRANT_API_KEY")),
#         ]
#         for label, value in rows:
#             st.markdown(
#                 f"""
#                 <div class="status-row">
#                   <span>{html.escape(label)}</span>
#                   <strong>{html.escape(str(value))}</strong>
#                 </div>
#                 """,
#                 unsafe_allow_html=True,
#             )


# st.set_page_config(page_title="Settings | Enterprise RAG", page_icon="R", layout="wide")
# load_styles()
# init_session_state()
# backend_health = _load_health()
# render_sidebar("Settings")

# st.markdown(
#     """
#     <style>
#       .page-title { font-size: 1.45rem !important; margin-bottom: 0.2rem !important; }
#       .page-subtitle { font-size: 0.9rem !important; margin-bottom: 0.85rem !important; }
#       [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px !important; background:#fff !important; box-shadow: 0 8px 20px rgba(15,27,61,.055); }
#       div[data-testid="stSlider"] { padding-top: 0 !important; padding-bottom: 0.25rem !important; }
#       div[data-testid="stTextInput"] input,
#       div[data-testid="stSelectbox"] [data-baseweb="select"] {
#         min-height: 36px !important;
#         font-size: 0.86rem !important;
#       }
#     </style>
#     """,
#     unsafe_allow_html=True,
# )

# st.markdown('<h1 class="page-title">Settings</h1>', unsafe_allow_html=True)
# st.markdown('<p class="page-subtitle">Configure your RAG system preferences.</p>', unsafe_allow_html=True)

# if not backend_health.get("success"):
#     st.markdown(
#         f"""
#         <div class="dashboard-card" style="border-color:#fecaca; background:#fff8f8;">
#           <h3>Backend unavailable</h3>
#           <p>{html.escape(backend_health.get("error", "Backend is not reachable."))}</p>
#         </div>
#         """,
#         unsafe_allow_html=True,
#     )

# left_col, right_col = st.columns(2, gap="large")
# with left_col:
#     _render_embedding_settings()
#     _render_chunking_settings()
#     _render_retrieval_settings()

# with right_col:
#     _render_llm_settings()
#     _render_api_configuration()
#     _render_key_sources()
#     _render_cache_settings()
#     _render_system_preferences(backend_health)



def _load_health() -> dict:
    try:
        st.session_state.backend_health = cached_health()
    except ApiClientError as exc:
        st.session_state.backend_health = {"success": False, "error": str(exc)}
    return st.session_state.backend_health


def _status_badge(label: str, ok: bool) -> None:
    css = "status-active" if ok else "status-error"
    st.markdown(f'<span class="status-badge {css}">{label}</span>', unsafe_allow_html=True)


def _sync_build_setting(ui_key: str, persistent_key: str) -> None:
    st.session_state[persistent_key] = st.session_state[ui_key]


def _render_embedding_settings() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>Embedding Settings</h3><p>Used by upload/build and collection attach flows.</p></div></div>', unsafe_allow_html=True)
        st.selectbox("Embedding provider", ["huggingface", "openai"], key="embedding_provider")


def _render_llm_settings() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>LLM Provider Settings</h3><p>OpenAI is the configured generation provider.</p></div></div>', unsafe_allow_html=True)
        quota_error = OPENAI_QUOTA_MESSAGE in str(st.session_state.get(LLM_FALLBACK_WARNING_KEY) or "")
        if quota_error:
            _status_badge("OpenAI Quota Error", False)
            st.error(OPENAI_QUOTA_MESSAGE)
        elif get_key_source("OPENAI_API_KEY") == "session":
            _status_badge("OpenAI Runtime Key Active", True)
        else:
            _status_badge("OpenAI Runtime Key Missing", False)
        st.caption("OpenAI API Key - Required for Upload + Chat")
        st.caption("Tavily API Key - Optional for Web Search")


def _render_chunking_settings() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>Chunking Settings</h3><p>Controls how uploaded documents are split.</p></div></div>', unsafe_allow_html=True)
        st.session_state.setdefault("settings_chunk_size", st.session_state["rag_chunk_size"])
        st.session_state.setdefault("settings_chunk_overlap", st.session_state["rag_chunk_overlap"])
        st.slider("Chunk size", 300, 1500, key="settings_chunk_size", step=50, on_change=_sync_build_setting, args=("settings_chunk_size", "rag_chunk_size"))
        st.slider("Chunk overlap", 0, 300, key="settings_chunk_overlap", step=10, on_change=_sync_build_setting, args=("settings_chunk_overlap", "rag_chunk_overlap"))
        for error in validate_build_settings():
            if error.startswith("Chunk overlap"):
                st.error(error)


def _render_retrieval_settings() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>Retrieval Settings</h3><p>Hybrid retrieval and answer quality controls.</p></div></div>', unsafe_allow_html=True)
        st.session_state.setdefault("settings_top_k", st.session_state["rag_top_k"])
        st.session_state.setdefault("settings_max_iterations", st.session_state["rag_max_iterations"])
        st.session_state.setdefault("settings_enable_grading", st.session_state["rag_enable_grading"])
        st.session_state.setdefault("settings_enable_evaluation", st.session_state["rag_enable_evaluation"])
        col1, col2 = st.columns(2, gap="small")
        with col1:
            st.slider("Top K", 1, 12, key="settings_top_k", on_change=_sync_build_setting, args=("settings_top_k", "rag_top_k"))
            st.checkbox("Enable grading", key="settings_enable_grading", on_change=_sync_build_setting, args=("settings_enable_grading", "rag_enable_grading"))
        with col2:
            st.slider("Max iterations", 1, 5, key="settings_max_iterations", on_change=_sync_build_setting, args=("settings_max_iterations", "rag_max_iterations"))
            st.checkbox("Enable evaluation", key="settings_enable_evaluation", on_change=_sync_build_setting, args=("settings_enable_evaluation", "rag_enable_evaluation"))
        for error in validate_build_settings():
            if not error.startswith("Chunk overlap"):
                st.error(error)


def _render_api_configuration() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>API Configuration</h3><p>Runtime keys resolve from session first, then .env.</p></div></div>', unsafe_allow_html=True)
        st.text_input("FastAPI base URL", value=API_BASE_URL, disabled=True)
        if has_required_keys():
            st.markdown('<span class="status-badge status-active">API configured</span>', unsafe_allow_html=True)
        else:
            render_api_key_setup_panel("settings")


def _render_key_sources() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>Key Sources</h3><p>Secrets are masked and never displayed in full.</p></div></div>', unsafe_allow_html=True)
        labels = {
            "OPENAI_API_KEY": "OpenAI API Key - Required for Upload + Chat",
            "TAVILY_API_KEY": "Tavily API Key - Optional for Web Search",
        }
        for name, item in required_keys_status().items():
            source = item["source"]
            badge = "ok" if source != "missing" else "warn"
            st.markdown(
                f"""
                <div class="status-row">
                  <span>{html.escape(labels.get(name, name))}</span>
                  <strong><span class="mini-chip {badge}">{source}</span> {html.escape(item["masked"])}</strong>
                </div>
                """,
                unsafe_allow_html=True,
            )
        maybe_request_key_reset()


def _render_cache_settings() -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>Cache Settings</h3><p>Backend cache controls will appear here when available.</p></div></div>', unsafe_allow_html=True)
        st.markdown('<div class="empty-state"><div><strong>No cache controls</strong><span>No configurable cache settings are available from backend.</span></div></div>', unsafe_allow_html=True)
        st.markdown('<br>', unsafe_allow_html=True)

def _render_system_preferences(backend_health: dict) -> None:
    with st.container(border=True):
        st.markdown('<div class="section-title"><div><h3>System Preferences</h3><p>Current runtime and backend state.</p></div></div>', unsafe_allow_html=True)
        rows = [
            ("Backend", "Online" if backend_health.get("success") else "Offline"),
            ("Vector DB", backend_health.get("vector_db_provider") or "-"),
            ("OpenAI API Key - Required for Upload + Chat", get_key_source("OPENAI_API_KEY")),
            ("Tavily API Key - Optional for Web Search", get_key_source("TAVILY_API_KEY")),
        ]
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


st.set_page_config(page_title="Settings | Enterprise RAG", page_icon="R", layout="wide")
load_styles()
_render_workspace_loader()
init_session_state()

if not is_authenticated():
    render_fullscreen_auth_gate()
    st.stop()

require_runtime_credentials("settings")
backend_health = _load_health()
render_sidebar("Settings")
st.markdown('<span class="rag-page-root settings-page-root"></span>', unsafe_allow_html=True)

st.markdown(
    """
    <style>
      .block-container:has(.settings-page-root) {
        max-width: 1180px !important;
        padding-left: 1.4rem !important;
        padding-right: 1.4rem !important;
      }

      .page-title {
        font-size: 1.45rem !important;
        margin-bottom: 0.2rem !important;
      }

      .page-subtitle {
        font-size: 0.9rem !important;
        margin-bottom: 0.85rem !important;
      }

      [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        background: #fff !important;
        box-shadow: 0 8px 20px rgba(15, 27, 61, .055);
      }

      div[data-testid="stSlider"] {
        padding-top: 0 !important;
        padding-bottom: 0.25rem !important;
      }

      div[data-testid="stTextInput"] input,
      div[data-testid="stSelectbox"] [data-baseweb="select"] {
        min-height: 36px !important;
        font-size: 0.86rem !important;
      }

      div[data-testid="stVerticalBlock"] {
        gap: 0.62rem !important;
      }

      .block-container:has(.settings-page-root) [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #dfe7f3 !important;
        min-width: 0 !important;
      }

      .block-container:has(.settings-page-root) .section-title {
        margin-bottom: 0.38rem !important;
      }

      .block-container:has(.settings-page-root) .section-title h3 {
        font-size: 0.94rem !important;
      }

      .block-container:has(.settings-page-root) .section-title p {
        display: none !important;
      }

      .block-container:has(.settings-page-root) .status-row span,
      .block-container:has(.settings-page-root) .status-row strong {
        font-size: 0.78rem !important;
      }

      .block-container:has(.settings-page-root) [data-testid="stExpander"] {
        border-color: #dbe4f0 !important;
        border-radius: 8px !important;
        box-shadow: none !important;
      }

      .block-container:has(.settings-page-root) [data-testid="stExpander"] summary {
        min-height: 34px !important;
        padding: 0.38rem 0.62rem !important;
      }

      .block-container:has(.settings-page-root) [data-testid="stExpander"] summary p {
        color: #0f1b3d !important;
        font-size: 0.84rem !important;
        font-weight: 780 !important;
      }

      .block-container:has(.settings-page-root) .empty-state {
        min-height: 70px !important;
        padding: 0.7rem !important;
      }

      @media (max-width: 900px) {
        .block-container:has(.settings-page-root) {
          padding-left: 0.9rem !important;
          padding-right: 0.9rem !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<h1 class="page-title">Settings</h1>', unsafe_allow_html=True)
with st.expander("Page Notes", expanded=False):
    st.markdown("Configure RAG behavior, runtime credentials, backend connectivity, and key source visibility.")

if not backend_health.get("success"):
    st.markdown(
        f"""
        <div class="dashboard-card" style="border-color:#fecaca; background:#fff8f8;">
          <h3>Backend unavailable</h3>
          <p>{html.escape(backend_health.get("error", "Backend is not reachable."))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

left_col, right_col = st.columns([1.03, 0.97], gap="medium")

with left_col:
    _render_embedding_settings()
    _render_chunking_settings()
    _render_retrieval_settings()

with right_col:
    _render_llm_settings()
    _render_api_configuration()
    with st.expander("Key Sources", expanded=False):
        _render_key_sources()
    with st.expander("System Preferences", expanded=False):
        _render_system_preferences(backend_health)
    with st.expander("Cache Settings", expanded=False):
        _render_cache_settings()
