import html
import logging
import re
from pathlib import Path

import streamlit as st

from components.auth_panel import require_login
from components.document_validator import validate_uploaded_document
from components.layout import (
    get_ui_openai_key,
    get_ui_tavily_key,
    init_session_state,
    load_styles,
    validate_build_settings,
)
from components.runtime_secrets import has_required_keys, require_runtime_credentials, runtime_secret_payload
from components.sidebar import render_sidebar
from services.api_client import (
    ApiClientError,
    cached_health,
    cached_list_collections,
    get_collection_build_summary,
    upload_document,
)


COLLECTION_PREFIX = "agentic_rag_enterprise"
logger = logging.getLogger(__name__)
SUMMARY_EMPTY_MESSAGE = "No build summary available for this collection yet."


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


def collection_name_from_file(uploaded_file) -> str:
    if not uploaded_file:
        return COLLECTION_PREFIX
    stem = Path(str(uploaded_file.name)).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return f"{COLLECTION_PREFIX}_{slug}" if slug else COLLECTION_PREFIX


def truncate_collection_name(name: str, max_len: int = 42) -> str:
    value = str(name or "")
    return value if len(value) <= max_len else f"{value[:max_len - 3]}..."


def _load_health() -> dict:
    try:
        st.session_state.backend_health = cached_health()
    except ApiClientError as exc:
        st.session_state.backend_health = {"success": False, "error": str(exc)}
    return st.session_state.backend_health


def _existing_collection_names() -> set[str]:
    try:
        return {
            item.get("display_name") or item.get("name") or item.get("collection_name")
            for item in cached_list_collections().get("collections", [])
            if item.get("display_name") or item.get("name") or item.get("collection_name")
        }
    except ApiClientError:
        return set()


def _render_api_status() -> None:
    st.markdown(
        """
        <div class="section-card">
          <div class="section-title"><div><h3>API Access</h3></div></div>
          <span class="status-badge status-active">API configured</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<br>', unsafe_allow_html=True)


def _render_upload_card():
    with st.container(border=True):
        st.markdown(
            '<div class="section-title"><div><h3>Upload Document</h3></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="upload-dropzone">
              <h3>Choose a source document</h3>
              <p>TXT, MD, PDF, DOCX, DOC, and CSV are supported.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown('<br>', unsafe_allow_html=True)
        uploaded_file = st.file_uploader(
            "Upload document",
            type=["txt", "md", "pdf", "docx", "doc", "csv"],
            label_visibility="collapsed",
            help="Markdown tables and CSV rows are kept together as table-aware chunks.",
        )
        valid_file, validation_message = validate_uploaded_document(uploaded_file)
        if uploaded_file:
            if valid_file:
                st.success(validation_message)
                st.caption(f"Selected file: {uploaded_file.name} - {uploaded_file.size / 1024:.1f} KB")
            else:
                st.error(validation_message)
        else:
            st.caption("Upload a valid document to activate the build button.")
    return uploaded_file, valid_file


def _render_settings_card(existing_names: set[str], uploaded_file) -> tuple[str, str]:
    with st.container(border=True):
        st.markdown(
            '<div class="section-title"><div><h3>Upload Settings</h3></div></div>',
            unsafe_allow_html=True,
        )
        suggested_collection = collection_name_from_file(uploaded_file)
        previous_suggestion = st.session_state.get("last_suggested_collection_name", "")
        current_name = st.session_state.get("upload_collection_name", "")
        if not current_name or current_name == previous_suggestion:
            st.session_state.upload_collection_name = suggested_collection
        st.session_state.last_suggested_collection_name = suggested_collection
        collection_name = st.text_input(
            "New collection name",
            key="upload_collection_name",
            help=st.session_state.get("upload_collection_name", ""),
        )
        st.selectbox(
            "Chunking strategy",
            ["Markdown table-aware recursive chunking"],
            disabled=True,
            help="Current backend ingestion strategy. This page does not change backend pipeline logic.",
        )
        embedding_provider = st.selectbox(
            "Embedding provider",
            ["huggingface", "openai"],
            index=0 if st.session_state.get("embedding_provider", "huggingface") == "huggingface" else 1,
            help="The same provider is used for ingestion and query retrieval.",
        )
        st.session_state.embedding_provider = embedding_provider
        duplicate = collection_name.strip() in existing_names if collection_name else False
        if duplicate:
            st.error("Collection already exists. Please choose another name.")
    return collection_name, embedding_provider


def _render_build_settings_summary() -> None:
    rows = [
        ("Chunk size", st.session_state["rag_chunk_size"]),
        ("Overlap", st.session_state["rag_chunk_overlap"]),
        ("Top K", st.session_state["rag_top_k"]),
        ("Iterations", st.session_state["rag_max_iterations"]),
        ("Grading", "Enabled" if st.session_state["rag_enable_grading"] else "Disabled"),
        ("Evaluation", "Enabled" if st.session_state["rag_enable_evaluation"] else "Disabled"),
    ]
    chips = "".join(
        f'<div class="upload-setting-chip"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>'
        for label, value in rows
    )
    st.markdown(
        f"""
        <div class="upload-settings-summary">
          <div class="section-title"><div><h3>Build Settings</h3></div></div>
          <div class="upload-setting-grid">{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<br>', unsafe_allow_html=True)
    st.page_link("pages/settings.py", label="Edit build settings")


def _render_workflow_state(valid_file: bool, build_ready: bool) -> None:
    upload_class = "ready" if valid_file else ""
    config_class = "ready" if build_ready else ""
    st.markdown(
        f"""
        <div class="workflow">
          <div class="workflow-step {upload_class}"><i></i><span>Document selected</span></div>
          <div class="workflow-step {config_class}"><i></i><span>Build settings ready</span></div>
          <div class="workflow-step"><i></i><span>Chunking</span></div>
          <div class="workflow-step"><i></i><span>Embedding</span></div>
          <div class="workflow-step"><i></i><span>Indexing in Qdrant</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_collection_build_summary() -> None:
    collection_name = (
        st.session_state.get("active_collection_name")
        or st.session_state.get("selected_collection")
        or st.session_state.get("collection_name")
    )
    if not collection_name:
        return

    try:
        payload = get_collection_build_summary(collection_name)
        summary = payload.get("summary")
        if summary:
            st.session_state.collection_build_summary = summary
    except ApiClientError as exc:
        summary = st.session_state.get("collection_build_summary")
        if not summary:
            st.warning(f"Build summary unavailable: {exc}")
            return

    if not summary:
        summary = st.session_state.get("collection_build_summary")
    if not summary:
        st.info(SUMMARY_EMPTY_MESSAGE)
        return

    units_value = summary.get("document_units_value")
    units = "N/A" if units_value is None else f"{units_value} {summary.get('document_units_label', '')}"
    rows = [
        ("Collection", summary.get("collection_name", "N/A")),
        ("Document", summary.get("document_name", "N/A")),
        ("File type", str(summary.get("file_type", "N/A")).upper()),
        ("Document units", units),
        ("Chunks created", summary.get("chunks_created", "N/A")),
        ("Vectors stored", summary.get("vectors_stored", "N/A")),
        ("Chunk size", summary.get("chunk_size", "N/A")),
        ("Overlap", summary.get("chunk_overlap", "N/A")),
        ("Embedding model", summary.get("embedding_model", "N/A")),
    ]
    chips = "".join(
        f'<div class="upload-setting-chip" title="{html.escape(str(value), quote=True)}"><span>{html.escape(str(label))}</span><strong>{html.escape(truncate_collection_name(str(value)) if label == "Collection" else str(value))}</strong></div>'
        for label, value in rows
    )
    st.markdown(
        f"""
        <div class="upload-settings-summary">
          <div class="section-title"><div><h3>Knowledge Base Summary</h3></div></div>
          <div class="upload-setting-grid">{chips}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _apply_upload_result(result: dict, embedding_provider: str) -> None:
    session_id = result.get("session_id")
    collection_name = result.get("collection_name")
    display_name = result.get("display_name") or collection_name
    if not session_id or not collection_name:
        raise ApiClientError("Upload completed, but backend did not return an active chat session.")
    st.session_state.session_id = session_id
    st.session_state.active_session_id = session_id
    st.session_state.collection_name = collection_name
    st.session_state.active_collection = display_name
    st.session_state.active_collection_display_name = display_name
    st.session_state.active_collection_name = collection_name
    st.session_state.selected_collection = collection_name
    st.session_state.attached_collection = collection_name
    st.session_state.chat_dropdown_collection = collection_name
    st.session_state.pop("chat_collection_selector", None)
    st.session_state.agent_ready = True
    st.session_state.attach_status = "attached"
    st.session_state.last_attach_error = None
    st.session_state.retrieval_mode = result.get("retrieval_mode", "dense + BM25 hybrid")
    st.session_state.retrieval_warning = result.get("retrieval_warning", "")
    st.session_state.filename = result.get("filename", "uploaded_document")
    st.session_state.embedding_provider = result.get("embedding_provider", embedding_provider)
    st.session_state.last_sources = []
    st.session_state.last_trace = []
    st.session_state.collection_build_summary = result.get("summary") or {
        "collection_name": collection_name,
        "document_name": result.get("filename", "uploaded_document"),
        "chunks_created": result.get("chunks") or result.get("chunk_count") or result.get("chunks_created", "N/A"),
        "vectors_stored": result.get("vectors") or result.get("vectors_stored") or result.get("points_count", "N/A"),
        "embedding_model": result.get("embedding_model") or result.get("embedding_provider", embedding_provider),
    }


def _run_upload(uploaded_file, collection_name: str, embedding_provider: str, summary_slot=None) -> None:
    loader = _render_workspace_loader(persistent=True)
    with st.status("Building knowledge base...", expanded=True) as status:
        try:
            settings_errors = validate_build_settings()
            if settings_errors:
                raise ApiClientError(" ".join(settings_errors))
            logger.info(
                "Upload build settings chunk_size=%s chunk_overlap=%s top_k=%s max_iterations=%s enable_grading=%s enable_evaluation=%s",
                st.session_state["rag_chunk_size"],
                st.session_state["rag_chunk_overlap"],
                st.session_state["rag_top_k"],
                st.session_state["rag_max_iterations"],
                st.session_state["rag_enable_grading"],
                st.session_state["rag_enable_evaluation"],
            )
            st.write("Uploading document")
            st.write("Chunking and embedding content")
            result = upload_document(
                uploaded_file=uploaded_file,
                collection_name=collection_name.strip(),
                chunk_size=st.session_state["rag_chunk_size"],
                chunk_overlap=st.session_state["rag_chunk_overlap"],
                k=st.session_state["rag_top_k"],
                max_iterations=st.session_state["rag_max_iterations"],
                enable_grading=st.session_state["rag_enable_grading"],
                enable_evaluation=st.session_state["rag_enable_evaluation"],
                openai_api_key=get_ui_openai_key(),
                tavily_api_key=get_ui_tavily_key(),
                qdrant_url=runtime_secret_payload()["qdrant_url"],
                qdrant_api_key=runtime_secret_payload()["qdrant_api_key"],
                embedding_provider=embedding_provider,
                use_existing_collection=False,
            )
            if result.get("skipped"):
                status.update(label="Document already exists", state="complete")
                st.warning(result.get("message", "Document already exists"))
            _apply_upload_result(result, embedding_provider)
            cached_list_collections.clear()
            st.write("Indexing complete")
            status.update(label="Upload complete", state="complete")
            if summary_slot is not None:
                with summary_slot:
                    _render_collection_build_summary()
            st.markdown('<div class="success-card">Knowledge base is ready.</div> <br>', unsafe_allow_html=True)
            
            st.page_link("pages/chat.py", label="Go to Chat")
        except ApiClientError as exc:
            status.update(label="Upload failed", state="error")
            st.error(str(exc))
        finally:
            loader.empty()


st.set_page_config(page_title="Upload Documents | Enterprise RAG", page_icon="R", layout="wide")
load_styles()
_render_workspace_loader()
init_session_state()

if not require_login("Upload"):
    st.stop()

require_runtime_credentials("upload")
render_sidebar("Upload")

st.markdown('<h1 class="page-title">Upload Documents</h1>', unsafe_allow_html=True)
with st.expander("Page Notes", expanded=False):
    st.markdown(
        """
        Upload documents into a named collection. Chunking, retrieval, grading, and evaluation settings come from the Settings page and are applied when the build starts.
        """
    )
st.markdown('<span class="rag-page-root upload-page-marker"></span>', unsafe_allow_html=True)
st.markdown(
    """
    <style>
      .block-container:has(.upload-page-marker) {
        max-width: 1180px !important;
        padding-left: 1.4rem !important;
        padding-right: 1.4rem !important;
      }

      .block-container:has(.upload-page-marker) .section-title {
        margin-bottom: 0.42rem !important;
      }

      .block-container:has(.upload-page-marker) .section-title h3 {
        font-size: 0.98rem !important;
        margin: 0 !important;
      }

      .block-container:has(.upload-page-marker) .section-title p {
        display: none !important;
      }

      .block-container:has(.upload-page-marker) .upload-dropzone {
        padding: 0.82rem 0.9rem !important;
        min-height: 72px !important;
      }

      .block-container:has(.upload-page-marker) .upload-dropzone h3 {
        font-size: 0.94rem !important;
        margin-bottom: 0.14rem !important;
      }

      .block-container:has(.upload-page-marker) .upload-dropzone p,
      .block-container:has(.upload-page-marker) [data-testid="stCaptionContainer"] {
        font-size: 0.78rem !important;
      }

      .block-container:has(.upload-page-marker) .workflow {
        gap: 0.36rem !important;
        margin: 0.55rem 0 !important;
      }

      .block-container:has(.upload-page-marker) .workflow-step {
        font-size: 0.78rem !important;
      }

      .block-container:has(.upload-page-marker) div[data-testid="stSlider"] {
        padding-top: 0 !important;
        padding-bottom: 0.15rem !important;
      }

      .block-container:has(.upload-page-marker) .upload-settings-summary {
        border: 1px solid rgba(203,213,225,0.8);
        background: #fff;
        border-radius: 12px;
        padding: 0.82rem 0.92rem;
        margin-bottom: 0.7rem;
        box-shadow: 0 8px 20px rgba(15,27,61,.055);
      }

      .block-container:has(.upload-page-marker) .upload-setting-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.45rem;
      }

      .block-container:has(.upload-page-marker) .upload-setting-chip {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.55rem;
        min-height: 34px;
        padding: 0.42rem 0.55rem;
        border: 1px solid rgba(226,232,240,0.95);
        border-radius: 9px;
        background: rgba(248,250,252,0.88);
        color: #475569;
        font-size: 0.78rem;
      }

      .block-container:has(.upload-page-marker) .upload-setting-chip strong {
        color: #001b4d;
        font-size: 0.84rem;
        white-space: nowrap;
      }

      .block-container:has(.upload-page-marker) [data-testid="stVerticalBlock"] {
        gap: 0.72rem !important;
      }

      @media (max-width: 900px) {
        .block-container:has(.upload-page-marker) {
          padding-left: 0.9rem !important;
          padding-right: 0.9rem !important;
        }

        .block-container:has(.upload-page-marker) .upload-setting-grid {
          grid-template-columns: 1fr;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

backend_health = _load_health()

if not backend_health.get("success"):
    st.markdown(
        f"""
        <div class="dashboard-card" style="border-color:#fecaca; background:#fff8f8; margin-bottom:1rem;">
          <h3>Backend unavailable</h3>
          <p>{html.escape(backend_health.get("error", "Backend is not reachable."))}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

existing_names = _existing_collection_names()

summary_slot = st.empty()
with summary_slot:
    _render_collection_build_summary()

main_left, main_right = st.columns([0.58, 0.42], gap="medium")
with main_left:
    uploaded_file, valid_file = _render_upload_card()
    collection_name, embedding_provider = _render_settings_card(existing_names, uploaded_file)

with main_right:
    _render_api_status()
    with st.container(border=True):
        st.markdown(
            '<div class="section-title"><div><h3>Build Status</h3></div></div>',
            unsafe_allow_html=True,
        )
        key_ready = has_required_keys()
        embedding_ready = embedding_provider != "openai" or key_ready
        name_ready = bool(collection_name and collection_name.strip())
        duplicate_collection = bool(collection_name and collection_name.strip() in existing_names)
        settings_errors = validate_build_settings()
        build_disabled = not valid_file or not key_ready or not name_ready or duplicate_collection or not embedding_ready or bool(settings_errors)

        _render_workflow_state(valid_file, not build_disabled)

        if not valid_file:
            st.caption("Upload a valid document to activate the build button.")
        elif not key_ready:
            st.caption("Complete API setup before building a collection.")
        elif not embedding_ready:
            st.caption("OpenAI embeddings require an OpenAI key source.")
        elif not name_ready:
            st.caption("Choose a collection name.")
        elif duplicate_collection:
            st.error("Collection already exists. Please choose another name.")
        elif settings_errors:
            for error in settings_errors:
                st.error(error)
        else:
            st.markdown('<span class="status-badge status-active">Ready to build</span>', unsafe_allow_html=True)

        submitted = st.button(
            "Upload and Build Knowledge Base",
            type="primary",
            disabled=bool(build_disabled),
            width="stretch",
        )

        if submitted:
            _run_upload(uploaded_file, collection_name, embedding_provider, summary_slot)
    _render_build_settings_summary()
