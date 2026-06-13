import html

import streamlit as st

from components.auth_panel import require_login
from components.layout import init_session_state, load_styles
from components.runtime_secrets import require_runtime_credentials
from components.sidebar import render_sidebar
from services.api_client import (
    ApiClientError,
    cached_list_collections,
    delete_collection,
    delete_collection_by_name,
    get_collection_build_summary,
    rebuild_bm25_index,
    select_collection,
)


EMPTY = "\u2014"


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


def _collection_name(item: dict) -> str:
    return str(item.get("collection_name") or item.get("name") or "")


def _display_name(item: dict) -> str:
    return str(item.get("display_name") or item.get("name") or item.get("collection_name") or "")


def truncate_collection_name(name: str, max_len: int = 42) -> str:
    value = str(name or "")
    return value if len(value) <= max_len else f"{value[:max_len - 3]}..."


def _field(item: dict, *names: str, fallback=EMPTY):
    for name in names:
        if item.get(name) not in (None, ""):
            return item.get(name)
    return fallback


def _load_collections() -> tuple[list[dict], str]:
    try:
        payload = cached_list_collections()
        collections = payload.get("collections", [])
        return collections if isinstance(collections, list) else [], ""
    except ApiClientError as exc:
        return [], str(exc)


def _attach_collection(selected: dict) -> None:
    name = _collection_name(selected)
    display_name = _display_name(selected) or name
    loader = _render_workspace_loader(persistent=True)
    try:
        attached = select_collection(
            name,
            st.session_state.get("embedding_provider", "huggingface"),
        )
        session_id = attached.get("session_id")
        collection_name = attached.get("collection_name") or name
        attached_display_name = attached.get("display_name") or display_name
        if not session_id:
            raise ApiClientError("Backend did not return a session id for the selected collection.")
        st.session_state.session_id = session_id
        st.session_state.active_session_id = session_id
        st.session_state.collection_name = collection_name
        st.session_state.active_collection = attached_display_name
        st.session_state.active_collection_display_name = attached_display_name
        st.session_state.active_collection_name = collection_name
        st.session_state.selected_collection = collection_name
        st.session_state.attached_collection = collection_name
        st.session_state.chat_dropdown_collection = collection_name
        st.session_state.pop("chat_collection_selector", None)
        st.session_state.agent_ready = True
        st.session_state.attach_status = "attached"
        st.session_state.last_attach_error = None
        st.session_state.retrieval_mode = attached.get("retrieval_mode", "dense + BM25 hybrid")
        st.session_state.retrieval_warning = attached.get("retrieval_warning", "")
        st.session_state.filename = attached.get("filename", "existing_qdrant_collection")
        st.session_state.embedding_provider = attached.get(
            "embedding_provider",
            st.session_state.get("embedding_provider", "huggingface"),
        )
        st.session_state.last_sources = []
        st.session_state.last_meta = {}
        st.success("Collection attached.")
    except ApiClientError as exc:
        st.session_state.attach_status = "failed"
        st.session_state.last_attach_error = str(exc).replace("Collection selection failed:", "").strip()
        st.error(f"Attach failed: {st.session_state.last_attach_error}")
    finally:
        loader.empty()


def _delete_collection(selected: dict) -> None:
    name = _collection_name(selected)
    try:
        if name:
            delete_collection_by_name(name)
        elif selected.get("session_id"):
            delete_collection(selected["session_id"])
        if st.session_state.session_id == selected.get("session_id") or st.session_state.collection_name == name:
            st.session_state.session_id = ""
            st.session_state.active_session_id = ""
            st.session_state.collection_name = ""
            st.session_state.active_collection = ""
            st.session_state.active_collection_display_name = ""
            st.session_state.active_collection_name = ""
            st.session_state.selected_collection = ""
            st.session_state.attached_collection = ""
            st.session_state.chat_dropdown_collection = ""
            st.session_state.pop("chat_collection_selector", None)
            st.session_state.agent_ready = False
            st.session_state.attach_status = "idle"
            st.session_state.filename = ""
            st.session_state.embedding_provider = "huggingface"
        st.session_state.collection_remove_success = "Collection removed successfully."
        st.rerun()
    except ApiClientError as exc:
        st.error(str(exc))


def _row_value(item: dict, *names: str) -> str:
    return str(_field(item, *names, fallback=EMPTY))


def _delete_key(item: dict, index: int) -> str:
    name = _display_name(item) or _collection_name(item) or "collection"
    session_id = item.get("session_id") or ""
    return f"delete_collection_{index}_{name}_{session_id}"


def _render_table(collections: list[dict]) -> None:
    if not collections:
        st.markdown(
            '<div class="empty-state compact"><div><strong>No collections found</strong><span>Create a collection from Upload to start chatting with documents.</span></div></div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div class="table-card compact-table-title">
          <h3>Collections</h3>
          <p>{len(collections)} collection(s)</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    header = st.columns([2.2, 1.6, 0.8, 0.8], gap="small")
    header[0].caption("Collection Name")
    header[1].caption("Vector DB / Description")
    header[2].caption("Chunks")
    header[3].caption("Actions")

    table_height = min(360, max(118, 38 * len(collections) + 12))
    with st.container(height=table_height, border=True):
        for index, item in enumerate(collections):
            cols = st.columns([2.2, 1.6, 0.8, 0.8], gap="small")
            name = _display_name(item) or EMPTY
            physical_name = _collection_name(item)
            display_name = truncate_collection_name(name)
            description = _row_value(item, "description", "summary", "source")
            chunks = _row_value(item, "chunks", "chunk_count", "vectors_count", "points_count")
            active_value = st.session_state.get("active_collection") or st.session_state.get("collection_name")
            active = active_value in {name, physical_name}
            active_html = ' <span class="mini-chip ok">active</span>' if active else ""

            with cols[0]:
                st.markdown(
                    f'<div class="collection-cell collection-name" title="{html.escape(name, quote=True)}">{html.escape(display_name)}{active_html}</div>',
                    unsafe_allow_html=True,
                )
            with cols[1]:
                st.markdown(f'<div class="collection-cell"><span class="mini-chip">{html.escape(description)}</span></div>', unsafe_allow_html=True)
            with cols[2]:
                st.markdown(f'<div class="collection-cell"><span class="mini-chip ok">{html.escape(chunks)}</span></div>', unsafe_allow_html=True)
            with cols[3]:
                if st.button("Remove", key=_delete_key(item, index), width="stretch"):
                    _delete_collection(item)

            if index < len(collections) - 1:
                st.markdown('<div class="collection-row-line"></div>', unsafe_allow_html=True)


def _render_collection_build_summary(collection_name: str) -> None:
    try:
        payload = get_collection_build_summary(collection_name)
    except ApiClientError as exc:
        st.caption(f"Build summary unavailable: {exc}")
        return

    summary = payload.get("summary")
    if not summary:
        st.info("No build summary available for this collection yet.")
        return

    units_value = summary.get("document_units_value")
    units = "N/A" if units_value is None else f"{units_value} {summary.get('document_units_label', '')}"
    st.markdown("#### Knowledge Base Summary")
    st.caption(
        " | ".join(
            [
                f"Document: {summary.get('document_name', EMPTY)}",
                f"Type: {str(summary.get('file_type', EMPTY)).upper()}",
                f"Units: {units}",
                f"Chunks: {summary.get('chunks_created', EMPTY)}",
                f"Vectors: {summary.get('vectors_stored', EMPTY)}",
                f"Chunk size: {summary.get('chunk_size', EMPTY)}",
                f"Overlap: {summary.get('chunk_overlap', EMPTY)}",
                f"Embedding: {summary.get('embedding_model', EMPTY)}",
            ]
        )
    )


st.set_page_config(page_title="Collections | Enterprise RAG", page_icon="R", layout="wide")
load_styles()
_render_workspace_loader()
init_session_state()

if not require_login("Collections management"):
    st.stop()

require_runtime_credentials("collections")
render_sidebar("Collections")
st.markdown('<span class="rag-page-root collections-page-root"></span>', unsafe_allow_html=True)

st.markdown(
    """
    <style>
      .block-container:has(.collections-page-root) {
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
      .compact-table-title {
        padding: 0.7rem 0.85rem !important;
        margin-top: 0.4rem;
        margin-bottom: 0.45rem;
      }
      .compact-table-title h3 {
        margin: 0 !important;
        font-size: 0.98rem !important;
      }
      .compact-table-title p {
        margin: 0.15rem 0 0 !important;
        color: #60708f !important;
        font-size: 0.78rem !important;
      }
      .collection-cell {
        min-height: 30px;
        display: flex;
        align-items: center;
        color: #334155;
        font-size: 0.82rem;
        line-height: 1.2;
        overflow-wrap: anywhere;
      }
      .collection-name {
        color: #0f1b3d;
        font-weight: 800;
        gap: 0.4rem;
      }
      .collection-row-line {
        height: 1px;
        background: #eef2f8;
        margin: 0.12rem 0 0.18rem;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: #e5eaf3 !important;
        border-radius: 14px !important;
        background: #ffffff !important;
      }
      .block-container:has(.collections-page-root) [data-testid="stVerticalBlock"] {
        gap: 0.62rem !important;
      }
      .block-container:has(.collections-page-root) .empty-state.compact {
        min-height: 74px !important;
        padding: 0.78rem !important;
      }
      .block-container:has(.collections-page-root) .section-title {
        margin-bottom: 0.52rem !important;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button {
        min-height: 28px !important;
        height: 28px !important;
        padding: 0.15rem 0.5rem !important;
        border-radius: 9px !important;
        font-size: 0.78rem !important;
        background: #fff7ed !important;
        border: 1px solid #fed7aa !important;
        color: #9a3412 !important;
        box-shadow: none !important;
        font-weight: 720 !important;
        line-height: 1.05 !important;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button p,
      div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button span {
        color: #9a3412 !important;
        font-weight: 720 !important;
        line-height: 1.05 !important;
        margin: 0 !important;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover {
        background: #ffedd5 !important;
        border-color: #fdba74 !important;
        color: #7c2d12 !important;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover p,
      div[data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover span {
        color: #7c2d12 !important;
      }
      div[data-testid="stTextInput"] input,
      div[data-testid="stSelectbox"] [data-baseweb="select"] {
        min-height: 36px !important;
        font-size: 0.86rem !important;
      }
      .st-key-collections_action_selector [data-baseweb="select"] input,
      .st-key-collections_action_selector [data-baseweb="select"] [contenteditable="true"] {
        caret-color: transparent !important;
        cursor: default !important;
      }
      @media (max-width: 900px) {
        .block-container:has(.collections-page-root) {
          padding-left: 0.9rem !important;
          padding-right: 0.9rem !important;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<h1 class="page-title">Collections</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="page-subtitle">Manage your document collections and their settings.</p>',
    unsafe_allow_html=True,
)

collections, error = _load_collections()
if error:
    error_html = (
        '<div class="dashboard-card" style="border-color:#fecaca; background:#fff8f8; margin-bottom:1rem;">'
        "<h3>Collections unavailable</h3>"
        f"<p>{html.escape(error)}</p>"
        "</div>"
    )
    st.markdown(error_html, unsafe_allow_html=True)

if st.session_state.get("collection_remove_success"):
    st.success(st.session_state.pop("collection_remove_success"))

type_values = sorted({str(item.get("type")) for item in collections if item.get("type")})

control_cols = st.columns([0.48, 0.2, 0.32], gap="small")
with control_cols[0]:
    query = st.text_input("Search collections", placeholder="Search collections...", label_visibility="collapsed")
with control_cols[1]:
    type_filter = "All Types"
    if type_values:
        type_filter = st.selectbox("Type", ["All Types"] + type_values, label_visibility="collapsed")
with control_cols[2]:
    st.caption("Create collections from Upload.")

filtered = collections
if query:
    query_lower = query.lower()
    filtered = [item for item in filtered if query_lower in _display_name(item).lower()]
if type_values and type_filter != "All Types":
    filtered = [item for item in filtered if str(item.get("type")) == type_filter]

if filtered:
    with st.container(border=True):
        st.markdown(
            '<div class="section-title"><div><h3>Collection Actions</h3><p>Attach a collection or rebuild its BM25 index.</p></div></div>',
            unsafe_allow_html=True,
        )
        options = [index for index, item in enumerate(filtered) if _collection_name(item)]
        with st.container(key="collections_action_selector"):
            selected_index = st.selectbox(
                "Selected collection",
                options,
                format_func=lambda index: f"{truncate_collection_name(_display_name(filtered[index]))} ({filtered[index].get('source', 'runtime')})",
            )
        selected = filtered[selected_index]
        action_cols = st.columns(2, gap="small")
        with action_cols[0]:
            if st.button("Attach Collection", type="primary", width="stretch"):
                _attach_collection(selected)
        with action_cols[1]:
            if st.button("Rebuild BM25 Index", width="stretch"):
                try:
                    result = rebuild_bm25_index(_collection_name(selected))
                    st.success(f"{result.get('message', 'BM25 index rebuilt.')} Chunks: {result.get('chunk_count', 0)}")
                except ApiClientError as exc:
                    st.error(str(exc))
        _render_collection_build_summary(_collection_name(selected))

_render_table(filtered)
