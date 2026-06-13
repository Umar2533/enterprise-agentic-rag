import streamlit as st

from components.auth_panel import (
    ensure_auth_state,
    handle_email_verification_query,
    require_login,
)
from components.layout import init_session_state, load_styles
from components.runtime_secrets import require_runtime_credentials
from components.sidebar import render_sidebar
from services.api_client import ApiClientError, cached_health, cached_list_collections, cached_memory_stats


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


def _safe_health() -> dict:
    if st.session_state.get("backend_health"):
        return st.session_state.backend_health
    try:
        st.session_state.backend_health = cached_health()
    except ApiClientError as exc:
        st.session_state.backend_health = {"success": False, "error": str(exc)}
    return st.session_state.backend_health


def _safe_collections() -> list[dict]:
    try:
        return cached_list_collections().get("collections", [])
    except ApiClientError as exc:
        st.session_state.collection_error = str(exc)
        return []


def _safe_memory_stats() -> dict:
    try:
        return cached_memory_stats()
    except ApiClientError:
        return {}


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _collection_name(item: dict) -> str:
    return item.get("collection_name") or item.get("name") or "Untitled collection"


def _collection_documents(item: dict) -> int:
    return _as_int(item.get("documents") or item.get("document_count") or item.get("files_count"), 0)


def _collection_chunks(item: dict) -> int:
    return _as_int(item.get("chunks") or item.get("chunk_count") or item.get("vectors_count") or item.get("points_count"), 0)


def _collection_size(item: dict) -> str:
    return str(item.get("size") or item.get("storage_size") or "n/a")


def _metric_card(title: str, value: str, delta: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
          <span>{title}</span>
          <strong>{value}</strong>
          <small>{delta}</small>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _recent_activity(collections: list[dict]) -> None:
    rows = [
        ("Document uploaded", "Latest files are ready for retrieval", "2 minutes ago"),
        ("Collection reindexed", f"{len(collections)} collections available", "15 minutes ago"),
        ("New chat session started", st.session_state.get("active_collection") or "No active collection", "1 hour ago"),
        ("BM25 index checked", "Hybrid retrieval layer available when index exists", "3 hours ago"),
        ("System sync completed", "Qdrant collection registry refreshed", "5 hours ago"),
    ]
    st.markdown('<div class="dashboard-card"><h3>Recent Activity</h3>', unsafe_allow_html=True)
    for title, detail, when in rows:
        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; gap:1rem; padding:0.72rem 0; border-bottom:1px solid #eef2f8;">
              <div>
                <div style="font-weight:800; color:#0f1b3d;">{title}</div>
                <div style="color:#60708f; font-size:0.84rem;">{detail}</div>
              </div>
              <div style="color:#60708f; font-size:0.78rem; white-space:nowrap;">{when}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _query_activity() -> None:
    st.markdown('<div class="dashboard-card"><h3>Query Activity</h3>', unsafe_allow_html=True)
    st.line_chart({"Queries": [420, 640, 510, 940, 520, 760, 590]}, height=260)
    st.markdown("</div>", unsafe_allow_html=True)


def _system_health_card(backend_health: dict) -> None:
    healthy = bool(backend_health.get("success"))
    status = "All Systems Operational" if healthy else "Backend Attention Required"
    badge_class = "status-active" if healthy else "status-error"
    rows = [
        ("API Server", "Healthy" if healthy else "Offline"),
        ("Vector Database", "Healthy" if healthy else "Unknown"),
        ("LLM Service", "Healthy" if backend_health.get("openai_configured") else "Key optional"),
        ("Storage", "Healthy"),
        ("Memory Service", "Healthy"),
    ]
    st.markdown(
        f"""
        <div class="dashboard-card">
          <h3>System Health</h3>
          <span class="status-badge {badge_class}">{status}</span>
        """,
        unsafe_allow_html=True,
    )
    for name, state in rows:
        color = "#18b26b" if state in {"Healthy", "Key optional"} else "#ef4444"
        st.markdown(
            f"""
            <div style="display:flex; justify-content:space-between; align-items:center; padding:0.72rem 0;">
              <span style="color:#0f1b3d;"><i class="status-dot" style="background:{color};"></i>&nbsp; {name}</span>
              <span style="color:{color}; font-weight:700;">{state}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _storage_usage() -> None:
    st.markdown(
        """
        <div class="dashboard-card">
          <h3>Storage Usage</h3>
          <div style="display:grid; place-items:center; padding:1.2rem 0;">
            <div style="width:132px; height:132px; border-radius:50%; background:conic-gradient(#4f46e5 0 68%, #eef2f8 68% 100%); display:grid; place-items:center;">
              <div style="width:86px; height:86px; border-radius:50%; background:#fff; display:grid; place-items:center; text-align:center;">
                <div><strong style="font-size:1.6rem; color:#0f1b3d;">68%</strong><br/><span style="color:#60708f;">Used</span></div>
              </div>
            </div>
          </div>
          <div class="sidebar-status-row" style="color:#60708f;"><span>Used</span><span>136 GB</span></div>
          <div class="sidebar-status-row" style="color:#60708f;"><span>Available</span><span>64 GB</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _quick_actions() -> None:
    st.markdown('<div class="dashboard-card"><h3>Quick Actions</h3>', unsafe_allow_html=True)
    actions = [
        ("Upload Documents", "pages/upload.py"),
        ("Create Collection", "pages/collections.py"),
        ("Start Chat", "pages/chat.py"),
        ("View Analytics", "pages/analytics.py"),
        ("System Settings", "pages/settings.py"),
    ]
    for label, target in actions:
        st.page_link(target, label=label)
    st.markdown("</div>", unsafe_allow_html=True)


def _top_collections(collections: list[dict]) -> None:
    sample = collections[:5]
    st.markdown('<div class="table-card"><h3>Top Collections</h3>', unsafe_allow_html=True)
    if not sample:
        st.caption("No collections found.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown(
        """
        <div class="table-row header">
          <div>Collection Name</div><div>Documents</div><div>Chunks</div><div>Size</div><div>Last Updated</div><div>Status</div><div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for item in sample:
        name = _collection_name(item)
        docs = _collection_documents(item)
        chunks = _collection_chunks(item)
        size = _collection_size(item)
        st.markdown(
            f"""
            <div class="table-row">
              <div style="font-weight:800;">{name}</div>
              <div>{docs}</div>
              <div>{chunks:,}</div>
              <div>{size}</div>
              <div>Recently</div>
              <div><span class="status-badge status-active">Active</span></div>
              <div class="action-dots">...</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_overview(backend_health: dict, collections: list[dict], memory: dict) -> None:
    total_documents = sum(_collection_documents(item) for item in collections)
    total_chunks = sum(_collection_chunks(item) for item in collections)
    query_logs = st.session_state.get("query_logs", [])
    healthy = bool(backend_health.get("success"))
    status_label = "Backend online" if healthy else "Backend unavailable"
    status_class = "status-active" if healthy else "status-error"

    st.markdown(
        f"""
        <section class="home-header">
          <div>
            <h1>Enterprise RAG</h1>
            <p>Manage document collections and ask questions from your knowledge base.</p>
          </div>
          <span class="status-badge {status_class}">{status_label}</span>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if not healthy:
        st.markdown(
            f"""
            <div class="home-alert">
              <strong>Backend unavailable</strong>
              <span>{backend_health.get("error", "Start FastAPI to enable live system metrics.")}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    metric_cols = st.columns(4)
    with metric_cols[0]:
        _metric_card("Collections", str(len(collections)), "Available")
    with metric_cols[1]:
        _metric_card("Documents", f"{total_documents:,}", "Indexed")
    with metric_cols[2]:
        _metric_card("Chunks", f"{total_chunks:,}", "Searchable")
    with metric_cols[3]:
        _metric_card("Queries", f"{len(query_logs) or memory.get('total_memories', 0):,}", "This session")

    action_col, health_col = st.columns([0.62, 0.38], gap="large")
    with action_col:
        st.markdown('<div class="dashboard-card home-actions"><h3>Actions</h3>', unsafe_allow_html=True)
        actions = [
            ("Upload documents", "pages/upload.py"),
            ("Open chat", "pages/chat.py"),
            ("Collections", "pages/collections.py"),
        ]
        cols = st.columns(len(actions))
        for col, (label, target) in zip(cols, actions):
            with col:
                st.page_link(target, label=label)
        st.markdown("</div>", unsafe_allow_html=True)

    with health_col:
        st.markdown('<div class="dashboard-card compact-health"><h3>System</h3>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="compact-health-row">
              <span>API Server</span>
              <strong>{'Healthy' if healthy else 'Offline'}</strong>
            </div>
            <div class="compact-health-row">
              <span>LLM Key</span>
              <strong>{'Configured' if backend_health.get('openai_configured') else 'Optional'}</strong>
            </div>
            <div class="compact-health-row">
              <span>Active Collection</span>
              <strong>{st.session_state.get('active_collection') or 'None'}</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    _top_collections(collections)


st.set_page_config(page_title="Overview | Enterprise RAG", page_icon="R", layout="wide")
load_styles()
_render_workspace_loader()
init_session_state()
ensure_auth_state()

if handle_email_verification_query("overview"):
    st.stop()

if not require_login("Overview"):
    st.stop()

backend_health = _safe_health()
require_runtime_credentials("overview")
collections = _safe_collections()
memory = _safe_memory_stats()
render_sidebar("Overview")
st.markdown('<span class="rag-page-root overview-page-root"></span>', unsafe_allow_html=True)

_render_overview(backend_health, collections, memory)
