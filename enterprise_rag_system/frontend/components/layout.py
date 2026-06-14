from pathlib import Path
import re

import streamlit as st

from components.runtime_secrets import (
    get_secret_value,
    get_key_source,
    init_runtime_secret_state,
    default_embedding_provider,
    render_compact_api_status,
)


COLLECTION_PREFIX = "agentic_rag_enterprise"


def collection_name_from_file(uploaded_file) -> str:
    if not uploaded_file:
        return COLLECTION_PREFIX
    stem = Path(str(uploaded_file.name)).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return f"{COLLECTION_PREFIX}_{slug}" if slug else COLLECTION_PREFIX


def load_styles() -> None:
    style_path = Path(__file__).resolve().parents[1] / "styles" / "style.css"
    st.markdown(f"<style>{style_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def init_session_state() -> None:
    defaults = {
        "messages": [],
        "chat_history": [],
        "app_graph": None,
        "session_id": "",
        "active_session_id": "",
        "active_collection": "",
        "active_collection_name": "",
        "selected_collection": "",
        "attached_collection": "",
        "agent_ready": False,
        "attach_status": "idle",
        "last_attach_error": None,
        "retrieval_mode": "unknown",
        "retrieval_warning": "",
        "collection_name": "",
        "filename": "",
        "last_trace": [],
        "last_sources": [],
        "last_answer": "",
        "last_meta": {},
        "collection_build_summary": None,
        "chat_export_pdf": None,
        "latest_pdf_bytes": b"",
        "latest_pdf_signature": "",
        "refs_panel_open": False,
        "query_logs": [],
        "active_query_log_id": "",
        "active_main_tab": "Chat",
        "current_page": "Chat",
        "sidebar_collapsed": False,
        "openai_api_key": "",
        "tavily_api_key": "",
        "settings_openai_api_key": "",
        "settings_tavily_api_key": "",
        "upload_openai_api_key": "",
        "upload_tavily_api_key": "",
        "embedding_provider": default_embedding_provider(),
        "pending_embedding_provider": default_embedding_provider(),
        "backend_health": {},
        "answer_length": "Short",
        "custom_max_words": 250,
        "auth_token": "",
        "auth_refresh_token": "",
        "auth_user": {},
        "auth_error": "",
        "auth_notice_reason": "",
        "auth_checked_token": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "rag_chunk_size" not in st.session_state:
        st.session_state["rag_chunk_size"] = 300
    if "rag_chunk_overlap" not in st.session_state:
        st.session_state["rag_chunk_overlap"] = 30
    if "rag_top_k" not in st.session_state:
        st.session_state["rag_top_k"] = 5
    if "rag_max_iterations" not in st.session_state:
        st.session_state["rag_max_iterations"] = 3
    if "rag_enable_grading" not in st.session_state:
        st.session_state["rag_enable_grading"] = True
    if "rag_enable_evaluation" not in st.session_state:
        st.session_state["rag_enable_evaluation"] = True
    init_runtime_secret_state()
    _sync_legacy_setting_aliases()


def validate_build_settings() -> list[str]:
    errors = []
    if int(st.session_state.get("rag_chunk_overlap", 0)) >= int(st.session_state.get("rag_chunk_size", 0)):
        errors.append("Chunk overlap must be less than chunk size.")
    if int(st.session_state.get("rag_top_k", 0)) < 1:
        errors.append("Top K must be at least 1.")
    if int(st.session_state.get("rag_max_iterations", 0)) < 1:
        errors.append("Max iterations must be at least 1.")
    return errors


def render_header(title: str, subtitle: str) -> None:
    active = st.session_state.get("active_collection") or st.session_state.get("collection_name") or "No active collection"
    st.markdown(
        f"""
        <div class="page-header">
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
            <span class="active-collection">Active: {active}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_runtime_sidebar() -> None:
    from components.sidebar import render_sidebar

    render_sidebar("Chat")


def _render_query_logs_sidebar() -> None:
    st.markdown("## RAG Query Logs")
    logs = st.session_state.get("query_logs", [])
    if not logs:
        st.caption("No query logs yet.")
    else:
        for index, log in enumerate(reversed(logs)):
            log_id = log.get("id") or f"missing_{index}"
            title = log.get("title") or "Untitled query"
            button_type = "primary" if log_id == st.session_state.get("active_query_log_id") else "secondary"
            if st.button(title, key=f"log_{log_id}", width="stretch", type=button_type):
                st.session_state.active_query_log_id = log_id
                st.session_state.active_main_tab = "Chat"
                st.session_state.current_page = "Chat"
                st.session_state.chat_export_pdf = None
                st.rerun()

    if logs and st.button("Clear Logs", key="clear_query_logs", width="stretch"):
        st.session_state.query_logs = []
        st.session_state.active_query_log_id = ""
        st.session_state.chat_export_pdf = None
        st.rerun()


def render_rag_controls_panel() -> None:
    st.markdown("Choose embedding provider and runtime RAG behavior.")
    with st.form("settings_form"):
        provider = st.selectbox(
            "Embedding provider",
            ["huggingface", "openai"],
            index=0 if st.session_state.get("embedding_provider", default_embedding_provider()) == "huggingface" else 1,
            key="pending_embedding_provider",
        )
        render_compact_api_status()
        applied = st.form_submit_button("Apply Settings", width="stretch")

    if applied:
        if not st.session_state.get("session_id"):
            st.session_state.embedding_provider = provider
        st.success("Settings applied.")


def render_collections_panel() -> None:
    st.markdown("Attach, refresh, or delete Qdrant collections.")
    _render_collection_selector()


def render_upload_build_panel() -> None:
    st.markdown("Upload a document and build a knowledge base.")
    _render_sidebar_upload()


def render_advanced_settings_panel() -> None:
    st.info("Advanced settings are managed inside Upload / Build.")


def render_session_panel() -> None:
    st.markdown("View session stats and clear chat.")
    active = st.session_state.get("active_collection") or "None"
    st.caption(f"Active collection: {active}")
    st.caption(f"Messages: {len(st.session_state.get('chat_history', []))}")
    st.caption(f"Last sources: {len(st.session_state.get('last_sources', []))}")
    if st.button("Clear chat", width="stretch"):
        st.session_state.chat_history = []
        st.session_state.messages = []
        st.session_state.last_answer = ""
        st.session_state.last_meta = {}
        st.session_state.last_sources = []
        st.success("Chat cleared.")


def backend_uses_env_key() -> bool:
    return get_key_source("OPENAI_API_KEY") == ".env"


def get_ui_openai_key() -> str:
    return get_secret_value("OPENAI_API_KEY")


def get_ui_tavily_key() -> str:
    return get_secret_value("TAVILY_API_KEY")


def has_openai_key_source() -> bool:
    return backend_uses_env_key() or bool(get_ui_openai_key())


def _render_collection_selector() -> None:
    try:
        from services.api_client import (
            ApiClientError,
            cached_list_collections,
            delete_collection,
            delete_collection_by_name,
            rebuild_bm25_index,
            select_collection,
        )
    except Exception:
        return

    try:
        collections = cached_list_collections().get("collections", [])
    except Exception:
        collections = []

    if not collections:
        st.info("No Qdrant collections found.")
        return

    labels = {
        f"{item['collection_name']} ({item.get('source', 'runtime')})": item
        for item in collections
    }
    label_list = list(labels.keys())
    selected_collection = st.session_state.get("selected_collection") or st.session_state.get("active_collection")
    current_index = 0
    for index, label in enumerate(label_list):
        if labels[label].get("collection_name") == selected_collection:
            current_index = index
            break

    selected_label = st.selectbox("Select collection", label_list, index=current_index)
    selected = labels[selected_label]
    selected_collection_name = selected.get("collection_name", "")
    previous_selection = st.session_state.get("selected_collection")
    st.session_state.selected_collection = selected_collection_name
    if previous_selection != selected_collection_name and st.session_state.get("attach_status") == "failed":
        st.session_state.attach_status = "idle"
        st.session_state.last_attach_error = None

    attached_collection = st.session_state.get("attached_collection") or st.session_state.get("active_collection")
    if attached_collection == selected_collection_name and st.session_state.get("session_id"):
        st.success(f"Active collection: {selected_collection_name} (attached)")
        st.caption(f"Retrieval: {st.session_state.get('retrieval_mode', 'unknown')}")
        if st.session_state.get("retrieval_warning"):
            st.warning(st.session_state.retrieval_warning)
    elif st.session_state.get("attach_status") == "failed" and st.session_state.get("last_attach_error"):
        st.error(f"Attach failed: {st.session_state.last_attach_error}")
    else:
        st.info(f"Selected collection: {selected_collection_name} - click Attach")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Attach Collection", width="stretch"):
            try:
                attached = select_collection(
                    selected_collection_name,
                    st.session_state.get("embedding_provider", default_embedding_provider()),
                )
                session_id = attached.get("session_id")
                collection_name = attached.get("collection_name") or selected_collection_name
                if not session_id:
                    raise ApiClientError("Backend did not return a session id for the selected collection.")
                st.session_state.session_id = session_id
                st.session_state.active_session_id = session_id
                st.session_state.collection_name = collection_name
                st.session_state.active_collection = collection_name
                st.session_state.active_collection_display_name = attached.get("display_name") or collection_name
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
                if attached.get("embedding_provider") not in {"", "unknown", None}:
                    st.session_state.embedding_provider = attached.get(
                        "embedding_provider",
                        default_embedding_provider(),
                    )
                st.session_state.last_sources = []
                st.success(f"Active collection: {collection_name} (attached)")
            except ApiClientError as exc:
                st.session_state.attach_status = "failed"
                st.session_state.last_attach_error = _friendly_error(str(exc))
                st.error(f"Attach failed: {st.session_state.last_attach_error}")
    with col2:
        if st.button("Delete Selected", width="stretch"):
            try:
                if selected.get("session_id"):
                    delete_collection(selected["session_id"])
                else:
                    delete_collection_by_name(selected_collection_name)
                if st.session_state.get("active_collection") == selected_collection_name:
                    st.session_state.session_id = ""
                    st.session_state.active_session_id = ""
                    st.session_state.active_collection = ""
                    st.session_state.active_collection_display_name = ""
                    st.session_state.active_collection_name = ""
                    st.session_state.attached_collection = ""
                    st.session_state.collection_name = ""
                    st.session_state.filename = ""
                    st.session_state.agent_ready = False
                    st.session_state.attach_status = "idle"
                st.session_state.selected_collection = ""
                st.success("Collection deleted.")
            except ApiClientError as exc:
                st.error(_friendly_error(str(exc)))

    if st.button("Rebuild BM25 Index", width="stretch"):
        try:
            result = rebuild_bm25_index(selected_collection_name)
            st.success(f"{result.get('message', 'BM25 index rebuilt.')} Chunks: {result.get('chunk_count', 0)}")
        except ApiClientError as exc:
            st.error(_friendly_error(str(exc)))


def _render_sidebar_upload() -> None:
    try:
        from components.document_validator import validate_uploaded_document
        from services.api_client import ApiClientError, cached_list_collections, upload_document
    except Exception:
        st.info("Upload is available from the Upload page.")
        return

    uploaded_file = st.file_uploader(
        "Upload document",
        type=["txt", "md", "pdf", "docx", "doc", "csv"],
        key="sidebar_upload_file",
    )
    valid_file, validation_message = validate_uploaded_document(uploaded_file)
    if uploaded_file:
        (st.success if valid_file else st.error)(validation_message)

    try:
        existing = {item["collection_name"] for item in cached_list_collections().get("collections", [])}
    except Exception:
        existing = set()

    suggested_collection = collection_name_from_file(uploaded_file)
    previous_suggestion = st.session_state.get("sidebar_last_suggested_collection_name", "")
    current_name = st.session_state.get("sidebar_upload_collection_name", "")
    if not current_name or current_name == previous_suggestion:
        st.session_state.sidebar_upload_collection_name = suggested_collection
    st.session_state.sidebar_last_suggested_collection_name = suggested_collection

    collection_name = st.text_input(
        "Collection name",
        key="sidebar_upload_collection_name",
    )
    use_existing = st.checkbox("Append to selected existing collection", value=False, key="sidebar_use_existing_collection")
    duplicate = bool(collection_name.strip() in existing and not use_existing)
    key_ready = backend_uses_env_key() or bool(get_ui_openai_key())
    disabled = not valid_file or not key_ready or not collection_name.strip() or duplicate

    if duplicate:
        st.error("Collection already exists. Choose another name or append to it.")
    elif not valid_file:
        st.caption("Upload a valid document to activate the build button.")
    elif not key_ready:
        st.caption("Add an OpenAI key in backend .env or RAG Controls.")
    else:
        st.caption("Ready to build knowledge base.")

    render_upload_build_settings()

    if st.button("Build Knowledge Base", disabled=disabled, width="stretch"):
        try:
            result = upload_document(
                uploaded_file=uploaded_file,
                collection_name=collection_name.strip(),
                chunk_size=st.session_state.rag_chunk_size,
                chunk_overlap=st.session_state.rag_chunk_overlap,
                k=st.session_state.rag_top_k,
                max_iterations=st.session_state.rag_max_iterations,
                enable_grading=st.session_state.rag_enable_grading,
                enable_evaluation=st.session_state.rag_enable_evaluation,
                openai_api_key="" if backend_uses_env_key() else get_ui_openai_key(),
                tavily_api_key=get_ui_tavily_key(),
                embedding_provider=st.session_state.get("embedding_provider", default_embedding_provider()),
                use_existing_collection=use_existing,
            )
            session_id = result.get("session_id")
            result_collection_name = result.get("collection_name") or collection_name.strip()
            if not session_id:
                raise ApiClientError("Upload completed, but backend did not return an active chat session.")
            st.session_state.session_id = session_id
            st.session_state.active_session_id = session_id
            st.session_state.collection_name = result_collection_name
            st.session_state.active_collection = result_collection_name
            st.session_state.active_collection_display_name = result.get("display_name") or result_collection_name
            st.session_state.active_collection_name = result_collection_name
            st.session_state.selected_collection = result_collection_name
            st.session_state.attached_collection = result_collection_name
            st.session_state.chat_dropdown_collection = result_collection_name
            st.session_state.pop("chat_collection_selector", None)
            st.session_state.agent_ready = True
            st.session_state.attach_status = "attached"
            st.session_state.last_attach_error = None
            st.session_state.retrieval_mode = result.get("retrieval_mode", "dense + BM25 hybrid")
            st.session_state.retrieval_warning = result.get("retrieval_warning", "")
            st.session_state.filename = result.get("filename", "uploaded_document")
            st.session_state.embedding_provider = result.get("embedding_provider", st.session_state.embedding_provider)
            st.session_state.last_sources = []
            st.success("Knowledge base is ready.")
        except ApiClientError as exc:
            st.error(_friendly_error(str(exc)))


def render_upload_build_settings() -> None:
    st.markdown("#### Build / retrieval settings")
    st.selectbox("Answer length", ["Short", "Medium", "Detailed", "Custom"], key="answer_length")
    if st.session_state.get("answer_length") == "Custom":
        st.number_input("Custom max words", min_value=50, max_value=1000, step=25, key="custom_max_words")

    col1, col2 = st.columns(2)
    with col1:
        st.slider("Chunk size", 300, 1500, key="sidebar_chunk_size", step=50)
        st.slider("Top K", 1, 12, key="sidebar_top_k")
        st.checkbox("Enable grading", key="sidebar_enable_grading")
    with col2:
        st.slider("Chunk overlap", 0, 300, key="sidebar_chunk_overlap", step=10)
        st.slider("Max iterations", 1, 5, key="sidebar_max_iterations")
        st.checkbox("Enable evaluation", key="sidebar_enable_evaluation")
    _sync_build_settings_from_legacy_aliases()
    for error in validate_build_settings():
        st.error(error)


def _friendly_error(message: str) -> str:
    cleaned = message.replace("Collection selection failed:", "").strip()
    if "does not contain dense vector named" in cleaned:
        return "This collection uses a different Qdrant vector name. Expected named vector 'dense'."
    return cleaned or "Operation failed. Please try again."


def get_answer_length_instruction() -> str:
    mode = st.session_state.get("answer_length", "Short")
    if mode == "Short":
        return "Short: 80-120 words"
    if mode == "Detailed":
        return "Detailed: 350-500 words"
    if mode == "Custom":
        return f"Custom: maximum {int(st.session_state.get('custom_max_words', 250))} words"
    return "Medium: 180-250 words"


def _render_settings_summary() -> None:
    st.markdown("#### Current settings")
    st.caption(
        " | ".join(
            [
                f"Answer length: {st.session_state.answer_length}",
                f"Chunk size: {st.session_state.rag_chunk_size}",
                f"Chunk overlap: {st.session_state.rag_chunk_overlap}",
                f"Top K: {st.session_state.rag_top_k}",
                f"Max iterations: {st.session_state.rag_max_iterations}",
                f"Grading: {'Enabled' if st.session_state.rag_enable_grading else 'Disabled'}",
                f"Evaluation: {'Enabled' if st.session_state.rag_enable_evaluation else 'Disabled'}",
            ]
        )
    )
    st.caption("Edit these in Upload / Build.")


def _sync_legacy_setting_aliases() -> None:
    st.session_state.sidebar_chunk_size = st.session_state.rag_chunk_size
    st.session_state.sidebar_chunk_overlap = st.session_state.rag_chunk_overlap
    st.session_state.sidebar_top_k = st.session_state.rag_top_k
    st.session_state.sidebar_max_iterations = st.session_state.rag_max_iterations
    st.session_state.sidebar_enable_grading = st.session_state.rag_enable_grading
    st.session_state.sidebar_enable_evaluation = st.session_state.rag_enable_evaluation
    st.session_state.answer_length_mode = st.session_state.answer_length


def _sync_build_settings_from_legacy_aliases() -> None:
    st.session_state.rag_chunk_size = st.session_state.sidebar_chunk_size
    st.session_state.rag_chunk_overlap = st.session_state.sidebar_chunk_overlap
    st.session_state.rag_top_k = st.session_state.sidebar_top_k
    st.session_state.rag_max_iterations = st.session_state.sidebar_max_iterations
    st.session_state.rag_enable_grading = st.session_state.sidebar_enable_grading
    st.session_state.rag_enable_evaluation = st.session_state.sidebar_enable_evaluation
