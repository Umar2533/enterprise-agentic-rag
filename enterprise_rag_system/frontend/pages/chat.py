import asyncio
import html

import hashlib
import json
import logging
import math
import re
import sys

import streamlit as st
import time

from components.export_utils import export_chat_to_pdf
from components.auth_panel import require_login
from components.layout import (
    get_answer_length_instruction,
    init_session_state,
    load_styles,
    render_runtime_sidebar,
)
from components.runtime_secrets import USE_OPENAI_KEY, get_secret_value, require_runtime_credentials
from services.api_client import (
    ApiClientDisconnect,
    ApiClientError,
    cached_list_collections,
    chat,
    chat_stream,
    select_collection,
    verify_collection_activation,
)


MAX_REFERENCES_PER_ANSWER = 2
logger = logging.getLogger(__name__)


def _is_safe_client_disconnect(exc: object) -> bool:
    current = exc
    seen = set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (ConnectionResetError, BrokenPipeError)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _install_windows_disconnect_handler() -> None:
    if sys.platform != "win32" or st.session_state.get("_chat_windows_disconnect_handler_installed"):
        return
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    previous_handler = loop.get_exception_handler()

    def handle_loop_exception(event_loop, context):
        exc = context.get("exception")
        details = f"{context.get('message', '')} {context.get('handle', '')}"
        if _is_safe_client_disconnect(exc) or "_ProactorBasePipeTransport._call_connection_lost" in details:
            reason = type(exc).__name__ if exc is not None else "proactor_connection_lost"
            logger.debug("Windows client connection closed: %s", reason)
            return
        if previous_handler is not None:
            previous_handler(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_loop_exception)
    st.session_state._chat_windows_disconnect_handler_installed = True


_install_windows_disconnect_handler()


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


def _agentic_caption(meta: dict) -> str:
    parts = []
    search_type = meta.get("search_type")
    retrieval_mode = meta.get("retrieval_mode")
    web_search_requested = bool(meta.get("allow_web_search") or meta.get("web_search_requested"))
    web_search_used = meta.get("web_search_used") is True or str(search_type) == "web_search"
    if search_type and (str(search_type) != "web_search" or web_search_requested or web_search_used):
        search_label = str(search_type).replace("_", " ")
        if str(search_type) == "web_search":
            label = "web search"
        elif str(search_type) == "hybrid":
            label = "hybrid retrieval"
        else:
            label = f"{search_label} retrieval"
        parts.append(label)
    if meta.get("web_search_used") is True and "web search" not in parts:
        parts.append("web search used")
    if meta.get("collection_relevance"):
        parts.append(f"scope: {meta['collection_relevance']}")
    if (web_search_requested or web_search_used) and meta.get("web_search_eligible") is False:
        parts.append("web search skipped")
    if meta.get("reranked") or meta.get("reranker_used") or meta.get("reranking"):
        parts.append("reranked context")
    if meta.get("streaming") or meta.get("response_mode") == "streaming":
        parts.append("streaming response")
    if meta.get("evaluation"):
        parts.append(f"agentic evaluation: {meta['evaluation']}")
    if meta.get("iteration_count") is not None:
        parts.append(f"{meta['iteration_count']} iteration")
    if meta.get("retrieved_docs_count") is not None:
        parts.append(f"{meta['retrieved_docs_count']} docs")
    if web_search_used and meta.get("web_results_count") is not None:
        parts.append(f"{meta['web_results_count']} web results")
    if meta.get("confidence_level"):
        parts.append(f"{meta['confidence_level']} confidence")
    if retrieval_mode:
        parts.append(str(retrieval_mode))
    llm_provider = meta.get("llm_provider")
    llm_model = meta.get("llm_model")
    if llm_provider:
        parts.append(f"LLM: {llm_provider}")
    if llm_model:
        parts.append(f"Model: {llm_model}")
    if meta.get("openai_requested") and meta.get("llm_fallback_status"):
        parts.append(f"OpenAI fallback: {meta['llm_fallback_status']}")
    if meta.get("error_reason"):
        parts.append(f"error_reason: {meta['error_reason']}")
    retriever = meta.get("retriever") or meta.get("retriever_info")
    if retriever:
        parts.append(str(retriever))
    trace_steps = meta.get("trace_steps") or []
    if (web_search_requested or web_search_used) and meta.get("web_search_requires_approval"):
        parts.append("web search available")
    elif (web_search_requested or web_search_used) and not meta.get("web_search_used") and any(
        str(step.get("node", "")) == "web_search"
        and "approval" not in str(step.get("message", "")).lower()
        for step in trace_steps
        if isinstance(step, dict)
    ):
        parts.append("web search attempted")
    return " | ".join(parts)


def normalize_agentic_metadata(message_or_result: dict | None, base: dict | None = None) -> dict:
    """Collect the backend's agentic fields without inventing unavailable values."""
    result = dict(base or {})
    payload = message_or_result if isinstance(message_or_result, dict) else {}
    nested = payload.get("meta") or payload.get("metadata") or payload.get("tags") or {}
    if isinstance(nested, dict):
        result.update(nested)
    aliases = {
        "evaluation": ("evaluation", "agentic_evaluation", "answer_evaluation"),
        "iteration_count": ("iteration_count", "iterations"),
        "retrieved_docs_count": ("retrieved_docs_count", "docs_count", "document_count"),
        "web_results_count": ("web_results_count", "web_result_count"),
        "confidence_level": ("confidence_level", "confidence"),
        "retrieval_mode": ("retrieval_mode", "retriever", "retriever_info"),
        "search_type": ("search_type",),
        "web_search_used": ("web_search_used",),
        "web_search_requested": ("web_search_requested", "allow_web_search"),
        "web_search_available": ("web_search_available",),
        "web_search_requires_approval": ("web_search_requires_approval",),
        "web_search_eligible": ("web_search_eligible",),
        "collection_relevance": ("collection_relevance",),
        "trace_steps": ("trace_steps",),
        "llm_provider": ("llm_provider", "effective_llm_provider"),
        "llm_model": ("llm_model",),
        "llm_fallback_warning": ("llm_fallback_warning",),
        "llm_fallback_status": ("llm_fallback_status",),
        "runtime_openai_active": ("runtime_openai_active",),
        "openai_requested": ("openai_requested", "use_openai"),
        "error_reason": ("error_reason",),
    }
    for target, keys in aliases.items():
        for key in keys:
            if key in payload and payload[key] is not None:
                result[target] = payload[key]
                break
    if not result.get("openai_requested"):
        result.pop("llm_fallback_status", None)
        result.pop("llm_fallback_warning", None)
    return result


def _save_query_log(question: str, answer: str, sources: list, meta: dict) -> None:
    logs = st.session_state.setdefault("query_logs", [])
    log_id = f"chat_{len(logs) + 1}"
    thread_snapshot = list(st.session_state.get("chat_history", []))
    assistant_index = max(0, len(thread_snapshot) - 1)
    user_index = max(0, assistant_index - 1)
    logs.append(
        {
            "id": log_id,
            "title": question[:45] + ("..." if len(question) > 45 else ""),
            "user_message_index": user_index,
            "assistant_message_index": assistant_index,
            "thread_snapshot": thread_snapshot,
            "messages": [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer, "sources": sources, "meta": meta, "tags": meta},
            ],
            "collection": st.session_state.get("active_collection") or st.session_state.get("collection_name"),
            "collection_name": st.session_state.get("collection_name") or st.session_state.get("active_collection_name"),
            "collection_display_name": st.session_state.get("active_collection_display_name") or st.session_state.get("active_collection"),
        }
    )
    st.session_state.active_query_log_id = log_id
    st.session_state.recent_scroll_seen_log_id = log_id


def _clear_visible_chat_thread() -> None:
    st.session_state.chat_history = []
    st.session_state.messages = []
    st.session_state.last_sources = []
    st.session_state.last_meta = {}
    st.session_state.chat_export_pdf = None
    st.session_state.latest_pdf_bytes = b""
    st.session_state.latest_pdf_signature = ""


def _collection_name(item: dict) -> str:
    return str(item.get("collection_name") or item.get("name") or "")


def _collection_display_name(item: dict) -> str:
    return str(item.get("display_name") or item.get("name") or item.get("collection_name") or "")


def _active_display_collection() -> str:
    return str(
        st.session_state.get("active_collection_display_name")
        or st.session_state.get("active_collection")
        or st.session_state.get("collection_name")
        or ""
    )


def _active_physical_collection() -> str:
    return str(
        st.session_state.get("collection_name")
        or st.session_state.get("active_collection_name")
        or st.session_state.get("attached_collection")
        or ""
    )


def _active_session_id() -> str:
    return str(st.session_state.get("active_session_id") or st.session_state.get("session_id") or "")


def _dropdown_collection() -> str:
    return str(st.session_state.get("chat_dropdown_collection") or "")


def _dropdown_matches_active_collection() -> bool:
    dropdown_collection = _dropdown_collection()
    return not dropdown_collection or dropdown_collection == _active_physical_collection()


def _collection_label(item: dict) -> str:
    name = _collection_display_name(item) or "Unnamed collection"
    source = item.get("source") or item.get("type") or item.get("filename") or item.get("file_name") or "collection"
    return f"{name} ({source})"


def _load_chat_collections() -> tuple[list[dict], str]:
    try:
        payload = cached_list_collections()
        collections = payload.get("collections", [])
        return collections if isinstance(collections, list) else [], ""
    except ApiClientError as exc:
        return [], str(exc)


def _activation_toast(message: str, icon: str) -> None:
    icon_map = {
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "info": "ℹ️",
        "?": "✅",
        "??": "⚠️",
        "": "⚠️",
    }
    toast_icon = icon_map.get(str(icon or ""), icon)
    if hasattr(st, "toast"):
        st.toast(message, icon=toast_icon)
        return
    placeholder = st.empty()
    if toast_icon == "✅":
        placeholder.success(message)
    elif toast_icon == "❌":
        placeholder.error(message)
    elif toast_icon == "ℹ️":
        placeholder.info(message)
    else:
        placeholder.warning(message)
    time.sleep(1.6)
    placeholder.empty()


def _chat_toast(message: str, icon: str = "⚠️") -> None:
    toast_icon = "⚠️" if icon in {"?", "??", ""} else icon
    if hasattr(st, "toast"):
        st.toast(message, icon=toast_icon)
        return
    placeholder = st.empty()
    placeholder.warning(message)
    time.sleep(1.4)
    placeholder.empty()


def _valid_question(prompt: str, active_collection: str | None) -> tuple[str, bool]:
    question = " ".join((prompt or "").strip().split())
    meaningful = "".join(ch for ch in question if ch.isalnum())
    return question, bool(active_collection and len(meaningful) >= 3)


def _is_activation_transient_error(exc: ApiClientError) -> bool:
    exception_type = str(getattr(exc, "exception_type", "") or type(exc).__name__).lower()
    message = str(exc).lower()
    return (
        "timeout" in exception_type
        or "readtimeout" in exception_type
        or "connecttimeout" in exception_type
        or "connectionerror" in exception_type
        or "connectionreseterror" in exception_type
        or "timed out" in message
        or "timeout" in message
        or "winerror 10054" in message
        or "forcibly closed" in message
    )


def _apply_attached_collection_state(attached: dict, selected_name: str, display_name: str) -> str:
    session_id = attached.get("session_id")
    collection_name = attached.get("collection_name") or selected_name
    active_display_name = attached.get("display_name") or display_name
    if not session_id:
        raise ApiClientError("Backend did not return a session id for the selected collection.")
    st.session_state.session_id = session_id
    st.session_state.active_session_id = session_id
    st.session_state.collection_name = collection_name
    st.session_state.active_collection = active_display_name
    st.session_state.active_collection_display_name = active_display_name
    st.session_state.active_collection_name = collection_name
    st.session_state.selected_collection = collection_name
    st.session_state.attached_collection = collection_name
    st.session_state.chat_dropdown_collection = collection_name
    st.session_state.collection_selected_at = attached.get("selected_at", "")
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
    st.session_state.latest_pdf_bytes = b""
    st.session_state.latest_pdf_signature = ""
    return str(session_id)


def _attach_chat_collection(selected: dict) -> bool:
    name = _collection_name(selected)
    display_name = _collection_display_name(selected) or name
    logger.info("activation_request_started selected_collection=%s", name)
    loader = _render_workspace_loader(persistent=True)
    try:
        attached = select_collection(
            name,
            selected.get("embedding_provider") or st.session_state.get("embedding_provider", "huggingface"),
        )
        collection_name = attached.get("collection_name") or name
        previous_collection = _active_physical_collection()
        session_id = _apply_attached_collection_state(attached, name, display_name)
        if previous_collection and previous_collection != collection_name:
            _clear_visible_chat_thread()
        logger.info(
            "activation_success=true selected_collection=%s active_collection_after_response=%s active_session_id=%s previous_collection=%s rerun_triggered=true",
            name,
            collection_name,
            session_id,
            previous_collection or "none",
        )
        _activation_toast("Collection activated", "success")
        return True
    except ApiClientError as exc:
        logger.warning(
            "activation_exception_type=%s activation_elapsed_seconds=%s activation_timeout_value=%s activation_status_code=%s selected_collection=%s",
            getattr(exc, "exception_type", "") or type(exc).__name__,
            getattr(exc, "elapsed_seconds", None),
            getattr(exc, "timeout_value", None),
            getattr(exc, "status_code", None),
            name,
        )
        if _is_activation_transient_error(exc):
            try:
                verified = verify_collection_activation(name)
            except ApiClientError as verify_exc:
                logger.warning(
                    "activation_timeout_verification_failed selected_collection=%s exception_type=%s status_code=%s",
                    name,
                    getattr(verify_exc, "exception_type", "") or type(verify_exc).__name__,
                    getattr(verify_exc, "status_code", None),
                )
            else:
                if verified.get("active") and verified.get("session_id"):
                    previous_collection = _active_physical_collection()
                    collection_name = verified.get("collection_name") or name
                    session_id = _apply_attached_collection_state(verified, name, display_name)
                    if previous_collection and previous_collection != collection_name:
                        _clear_visible_chat_thread()
                    logger.info(
                        "activation_success=true selected_collection=%s active_collection_after_response=%s active_session_id=%s previous_collection=%s rerun_triggered=true activation_recovered_after_timeout=true",
                        name,
                        collection_name,
                        session_id,
                        previous_collection or "none",
                    )
                    _activation_toast("Collection activated after verification.", "success")
                    return True
        st.session_state.attach_status = "failed"
        st.session_state.last_attach_error = str(exc).replace("Collection selection failed:", "").strip()
        logger.warning(
            "activation_success=false selected_collection=%s active_collection_after_response=%s rerun_triggered=false",
            name,
            _active_physical_collection() or "none",
        )
        lowered_error = st.session_state.last_attach_error.lower()
        if (
            "api key is required" in lowered_error
            or ("invalid or missing api key" in lowered_error and not get_secret_value("BACKEND_API_KEY"))
        ):
            _activation_toast("API key is required to activate collections.", "warning")
        elif (
            "invalid or expired authentication token" in lowered_error
            or "invalid api key" in lowered_error
            or "invalid or missing api key" in lowered_error
        ):
            _activation_toast("Invalid API key. Please update API Access key.", "warning")
        elif "10060" in st.session_state.last_attach_error:
            _activation_toast("Connection timeout while activating collection. Please retry once.", "warning")
        elif _is_activation_transient_error(exc):
            _activation_toast("Connection reset while activating collection. Retried once.", "warning")
        else:
            _activation_toast(f"Could not activate collection: {st.session_state.last_attach_error}", "warning")
        return False
    finally:
        loader.empty()


def _render_collection_selector() -> None:
    collections, error = _load_chat_collections()
    active_physical_collection = st.session_state.get("collection_name") or st.session_state.get("active_collection_name")
    active_collection = st.session_state.get("active_collection") or active_physical_collection

    st.markdown(
        """
        <style>
        .chat-collection-card {
            margin: 0 !important;
            padding: 6px 0 8px 0 !important;
        }
        .st-key-chat_collection_selector {
            margin: 0 !important;
        }
        .st-key-chat_collection_selector [data-baseweb="select"] {
            padding: 4px 8px !important;
            font-size: 0.85rem !important;
        }
        .st-key-chat_collection_selector [data-baseweb="select"] input {
            caret-color: transparent !important;
            cursor: default !important;
        }
        .st-key-chat_collection_selector [data-baseweb="select"] [contenteditable="true"] {
            caret-color: transparent !important;
            cursor: default !important;
        }
        .st-key-chat_activate_collection button {
            height: 32px !important;
            font-size: 0.8rem !important;
            padding: 4px 12px !important;
        }
        </style>
        <div class="chat-collection-card">
        """,
        unsafe_allow_html=True,
    )
    
    if error:
        st.error(f"Collections unavailable: {error}")
    elif not collections:
        st.info("No collections found. Create a collection from the Upload page.")
    else:
        names = [_collection_name(item) for item in collections]
        labels = [_collection_display_name(item) for item in collections]
        active_index = next(
            (
                index
                for index, name in enumerate(names)
                if name == active_physical_collection or labels[index] == active_collection
            ),
            0,
        )
        select_col, button_col = st.columns([1, 0.2], gap="small")
        with select_col:
            selected = st.selectbox(
                "Collection",
                collections,
                index=active_index,
                format_func=_collection_label,
                label_visibility="collapsed",
                key="chat_collection_selector",
            )
            selected_name = _collection_name(selected)
            st.session_state.chat_dropdown_collection = selected_name
            logger.info(
                "Collection dropdown selected=%s active_collection=%s active_session_id=%s",
                selected_name,
                _active_physical_collection() or "none",
                _active_session_id() or "none",
            )
        with button_col:
            st.markdown('<span class="activate-collection-anchor"></span>', unsafe_allow_html=True)
            if st.button("Activate", key="chat_activate_collection", width="stretch"):
                if _attach_chat_collection(selected):
                    st.rerun()

    active_collection = st.session_state.get("active_collection") or st.session_state.get("collection_name")
    st.markdown("</div>", unsafe_allow_html=True)


def _message_content_html(content: str) -> str:
    escaped = html.escape(content or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped.replace("\n", "<br>")


def _bubble_html(content: str, role: str, streaming: bool = False) -> str:
    bubble_class = "chat-bubble-user" if role == "user" else "chat-bubble-ai"
    cursor = '<span class="streaming-cursor"></span>' if streaming else ""
    return (
        f'<div class="message-row streaming-row {html.escape(role)}">'
        f'<div class="{bubble_class} {html.escape(role)}">{_message_content_html(content)}{cursor}</div>'
        "</div>"
    )


def _render_chat_autoscroll() -> None:
    st.session_state.chat_scroll_marker = int(st.session_state.get("chat_scroll_marker", 0)) + 1
    st.markdown(
        f'<span class="chat-scroll-anchor" data-scroll-marker="{st.session_state.chat_scroll_marker}"></span>'
        f'<button class="chat-scroll-focus" type="button" tabindex="-1" autofocus '
        f'aria-label="Latest message {st.session_state.chat_scroll_marker}"></button>',
        unsafe_allow_html=True,
    )


def _render_recent_selection_scroll(log_id: str) -> None:
    st.session_state.recent_scroll_seen_log_id = log_id
    safe_log_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(log_id or "recent"))
    st.markdown(
        f'<span class="chat-recent-scroll-anchor" data-recent-log="{html.escape(safe_log_id)}"></span>'
        f'<button class="chat-scroll-focus" type="button" tabindex="-1" autofocus '
        f'aria-label="Selected recent message"></button>',
        unsafe_allow_html=True,
    )


def _render_chat_bottom_spacer() -> None:
    st.markdown(
        '<div class="chat-bottom-safe-space">'
        '<span class="chat-scroll-anchor"></span>'
        '</div>',
        unsafe_allow_html=True,
    )


def _caption_html(meta: dict) -> str:
    caption = _agentic_caption(meta or {})
    if not caption:
        return ""
    return f'<div class="agentic-caption">{html.escape(caption)}</div>'


def _caption_chips_html(caption: str) -> str:
    parts = [part.strip() for part in str(caption or "").split("|") if part.strip()]
    if not parts:
        return ""
    chip_html = []
    for part in parts:
        chip_class = " scope-bad" if part.lower() == "scope: unrelated" else ""
        chip_html.append(f'<span class="{chip_class.strip()}">{html.escape(part)}</span>')
    chips = "".join(chip_html)
    return f'<div class="caption">{chips}</div>'


def _message_component_height(content: str, role: str, meta: dict | None = None) -> int:
    width_chars = 82 if role == "assistant" else 92
    lines = 0
    for line in str(content or "").splitlines() or [""]:
        lines += max(1, math.ceil(len(line) / width_chars))
    caption_rows = 1 if role == "assistant" and _agentic_caption(meta or {}) else 0
    return max(32, 20 + lines * 18 + caption_rows * 14)

def render_copyable_html(html_body: str, height: int) -> None:
    st.markdown(html_body, unsafe_allow_html=True)

def _render_inline_copy_action(text: str, key: str, role: str) -> None:
    if not str(text or "").strip():
        return
    label = "Copy answer" if role == "assistant" else "Copy"
    safe_key = f"copy_{role}_" + re.sub(r"[^a-zA-Z0-9_-]+", "_", key)
    with st.container(key=safe_key):
        st.markdown(f'<span class="copy-action-label">{html.escape(label)}</span>', unsafe_allow_html=True)
        # Using st.code provides a browser-native copy button that works on deployed instances.
        st.code(text or "", language=None)


def render_message_card(role: str, content: str, key: str, meta: dict | None = None, highlighted: bool = False) -> None:
    bubble_class = "user" if role == "user" else "assistant"
    component_id = "chat_msg_" + re.sub(r"[^a-zA-Z0-9_-]+", "_", key)
    body = _message_content_html(content or "").strip()
    caption = _agentic_caption(meta or {}) if role == "assistant" else ""
    caption_html = _caption_chips_html(caption)
    align = "flex-end" if bubble_class == "user" else "flex-start"
    bubble_width = "fit-content" if bubble_class == "user" else "100%"
    max_width = "520px" if bubble_class == "user" else "none"
    radius = "16px 16px 6px 16px" if bubble_class == "user" else "16px 16px 16px 6px"
    border = "rgba(17, 24, 39, 0.12)" if bubble_class == "user" else "rgba(17, 24, 39, 0.10)"
    background = "#2f3136" if bubble_class == "user" else "#ffffff"
    color = "#ffffff" if bubble_class == "user" else "#1a1a1a"
    shadow = (
        "0 6px 14px rgba(17, 24, 39, 0.08)"
        if bubble_class == "user"
        else "0 6px 18px rgba(17, 24, 39, 0.04)"
    )
    copy_bg = "rgba(255, 255, 255, 0.22)" if bubble_class == "user" else "rgba(255, 255, 255, 0.88)"
    copy_color = "#ffffff" if bubble_class == "user" else "#64748b"
    copy_hover_bg = "rgba(255, 255, 255, 0.32)" if bubble_class == "user" else "#f8fafc"
    copy_hover_color = "#ffffff" if bubble_class == "user" else "#111827"
    row_style = (
        "background:#fff7ed; outline:1px solid #fed7aa; border-radius:18px; padding:6px; scroll-margin-top:96px;"
        if highlighted
        else ""
    )
    component_html = f"""
      <style>
        #{component_id} {{
          display: flex;
          flex-direction: column;
          align-items: {align};
          padding: 0 0 2px;
          background: transparent;
          font-family: Inter, "Segoe UI", Arial, sans-serif;
        }}
        #{component_id} .bubble {{
          position: relative;
          box-sizing: border-box;
          width: {bubble_width};
          max-width: {max_width};
          border-radius: {radius};
          border: 1px solid {border};
          background: {background};
          color: {color};
          padding: 16px 42px 16px 16px;
          box-shadow: {shadow};
          overflow-wrap: anywhere;
          font-size: 14px;
          line-height: 1.5;
          letter-spacing: 0;
        }}
        #{component_id} .bubble strong {{
          font-weight: 720;
        }}
        #{component_id} .copy-btn {{
          position: absolute;
          right: 7px;
          top: 7px;
          width: 24px;
          height: 24px;
          display: grid;
          place-items: center;
          border: 1px solid {border};
          border-radius: 999px;
          background: {copy_bg};
          color: {copy_color};
          cursor: pointer;
          opacity: 0.58;
          font-size: 12px;
          line-height: 1;
          transition: opacity 0.16s ease, background 0.16s ease, color 0.16s ease, transform 0.16s ease, box-shadow 0.16s ease;
          padding: 0;
        }}
        #{component_id} .copy-btn::before {{
          content: "?";
          display: block;
          transform: translateY(-0.5px);
        }}
        #{component_id} .bubble:hover .copy-btn,
        #{component_id} .copy-btn:focus {{
          opacity: 1;
        }}
        #{component_id} .copy-btn:hover {{
          background: {copy_hover_bg};
          color: {copy_hover_color};
          transform: translateY(-1px);
          box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
        }}
        #{component_id} .copy-btn.copied {{
          color: #047857;
          border-color: #86efac;
          background: #ecfdf5;
          opacity: 1;
        }}
        #{component_id} .copy-btn.copied::before {{
          content: "?";
        }}
        #{component_id} .caption {{
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
          max-width: 82%;
          margin: 4px 0 0 8px;
          color: #5f6673;
          font-size: 11px;
          line-height: 1.25;
        }}
        #{component_id} .caption span {{
          display: inline-flex;
          align-items: center;
          min-height: 18px;
          padding: 1px 6px;
          border: 1px solid #e5e7eb;
          border-radius: 999px;
          background: #f8fafc;
          color: #4b5563;
          white-space: nowrap;
        }}
        #{component_id} .caption span.scope-bad {{
          border-color: #fecaca;
          background: #fef2f2;
          color: #b91c1c;
        }}
      </style>
      <div id="{component_id}" class="message-row {bubble_class}" style="{row_style}">
        <div class="bubble chat-bubble-{"user" if bubble_class == "user" else "ai"}">{body}</div>
        {caption_html}
      </div>
    """
    render_copyable_html(component_html, height=_message_component_height(content, role, meta) + (14 if highlighted else 0))
    _render_inline_copy_action(content or "", key, bubble_class)


def _render_messages(messages: list[dict]) -> None:
    active_log_id = st.session_state.get("active_query_log_id")
    active_log = next(
        (
            log for log in st.session_state.get("query_logs", [])
            if log.get("id") == active_log_id
        ),
        {},
    )
    highlighted_indexes = {
        index for index in (active_log.get("user_message_index"), active_log.get("assistant_message_index"))
        if isinstance(index, int)
    }
    fallback_pair = active_log.get("messages", []) if not highlighted_indexes else []
    fallback_user = next((msg.get("content") for msg in fallback_pair if msg.get("role") == "user"), None)
    fallback_assistant = next((msg.get("content") for msg in fallback_pair if msg.get("role") == "assistant"), None)
    fallback_user_used = False
    fallback_assistant_used = False
    should_scroll_recent = bool(active_log_id and active_log_id != st.session_state.get("recent_scroll_seen_log_id"))
    recent_scroll_rendered = False
    for message_index, message in enumerate(messages):
        role = message.get("role", "assistant")
        if role in ("user", "assistant"):
            content = message.get("content", "")
            highlighted = message_index in highlighted_indexes
            if not highlighted_indexes and role == "user" and content == fallback_user and not fallback_user_used:
                highlighted = True
                fallback_user_used = True
            elif not highlighted_indexes and role == "assistant" and content == fallback_assistant and fallback_user_used and not fallback_assistant_used:
                highlighted = True
                fallback_assistant_used = True
            if highlighted and should_scroll_recent and not recent_scroll_rendered:
                _render_recent_selection_scroll(str(active_log_id))
                recent_scroll_rendered = True
            render_message_card(
                role,
                content,
                key=f"chat_message_{message_index}_{role}",
                meta=message.get("meta", {}),
                highlighted=highlighted,
            )


def _render_empty_conversation(active_collection: str | None) -> None:
    st.markdown(
        """
        <div class="chat-empty-state">
          <strong>Ready for your documents</strong>
          <span>Activate a collection, then ask a question.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _suggestion_prompts() -> list[tuple[str, str]]:
    return [
        ("Summarize", "Summarize this document"),
        ("Key insights", "Extract key insights"),
        ("Compare", "Compare sections"),
        ("Action items", "Find important action items"),
        ("Main risks", "What are the main risks mentioned?"),
        ("Key terms", "Explain the key terms"),
        ("Timeline", "Build a timeline of events"),
        ("Bullet brief", "Give a short bullet-point brief"),
        ("Decisions", "What decisions are documented?"),
        ("FAQ", "List the main questions and answers from this content"),
        ("Glossary", "Create a glossary of important terms"),
        ("Next steps", "What are the recommended next steps?"),
        ("Who & what", "Who and what are the main entities mentioned?"),
        ("Conclusion", "What is the main conclusion?"),
        ("Data points", "List the key data points and numbers"),
        ("Explain", "Explain this in simple language"),
    ]


def _render_suggestion_chips(active_collection: str | None) -> None:
    existing_messages = st.session_state.get("chat_history") or st.session_state.get("messages") or []
    if existing_messages:
        return

    prompts = _suggestion_prompts()
    session_ready = bool(st.session_state.get("session_id") and active_collection)
    with st.container(key="chat_suggestions_bar"):
        cols = st.columns(len(prompts), gap="small")
        for index, (label, prompt) in enumerate(prompts):
            with cols[index]:
                if st.button(label, key=f"chat_suggestion_{index}", disabled=not session_ready):
                    st.session_state.chat_reuse_query = prompt
                    st.rerun()


def _source_value(source: dict, metadata: dict, *names: str, fallback: str = "n/a") -> str:
    for name in names:
        value = source.get(name)
        if value not in (None, ""):
            return str(value)
        value = metadata.get(name)
        if value not in (None, ""):
            return str(value)
    return fallback


def _as_list(value) -> list:
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def _source_content(source: dict) -> str:
    return str(
        source.get("content")
        or source.get("page_content")
        or source.get("text")
        or source.get("chunk")
        or source.get("snippet")
        or source.get("summary")
        or ""
    )


def _source_title(source: dict, index: int) -> str:
    metadata = source.get("metadata", {}) or {}
    if _is_web_source(source):
        title = _source_value(source, metadata, "title", "url", "source", fallback=f"Web result {index}")
        return f"Web Search: {title}"
    return _source_value(
        source,
        metadata,
        "file_name",
        "filename",
        "document_name",
        "source",
        "title",
        "url",
        fallback="Source chunk",
    )


def _source_preview(source: dict) -> str:
    preview = " ".join(_source_content(source).split())
    return preview[:140] + ("..." if len(preview) > 140 else "")


def extract_chunk_keyword(chunk_text: str, fallback: str = "Chunk") -> str:
    text = re.sub(r"\s+", " ", str(chunk_text or "")).strip()
    if not text:
        return fallback
    title_word = re.search(r"\b[A-Z][A-Za-z0-9+-]{2,}\b", text)
    if title_word:
        return title_word.group(0)[:12]
    stop_words = {
        "the", "and", "for", "with", "from", "that", "this", "into", "are", "were", "was", "have", "has",
        "their", "there", "such", "when", "then", "than", "also", "will", "would", "should", "could",
        "document", "documents", "chunk", "text", "user", "asks", "question", "system",
    }
    words = [word for word in re.findall(r"[A-Za-z][A-Za-z0-9+-]+", text) if word.lower() not in stop_words]
    if not words:
        return fallback
    return words[0].title()[:12]


def _reference_label(source: dict, index: int) -> str:
    metadata = source.get("metadata", {}) or {}
    if source.get("source_type") == "web_search" or metadata.get("source_type") == "web_search":
        return f"Web Search {index}"
    keyword = extract_chunk_keyword(_source_content(source), fallback=f"Chunk {index}")
    return f"Ref {index}: {keyword}"


def _source_score(source: dict) -> str:
    metadata = source.get("metadata", {}) or {}
    return _source_value(source, metadata, "retrieval_score", "score", fallback="")


def _message_sources(message: dict) -> list[dict]:
    sources = []
    for field in ("sources", "references", "documents", "contexts", "retrieved_docs", "trace_steps", "web_results"):
        for item in _as_list(message.get(field)):
            if isinstance(item, dict):
                sources.append(item)
            elif item:
                sources.append({"content": str(item)})

    meta = message.get("meta") or message.get("tags") or {}
    for item in _as_list(meta.get("trace_steps")):
        if isinstance(item, dict) and any(item.get(key) for key in ("content", "page_content", "text", "snippet")):
            sources.append(item)
    return sources


def _payload_sources(payload: dict, fallback: list[dict] | None = None) -> list[dict]:
    sources = _message_sources(payload or {})
    return sources if sources else (fallback or [])


def _recover_non_streaming_answer(
    session_id: str,
    question: str,
    answer_length: str,
    allow_web_search: bool,
    collection_name: str,
    meta: dict,
    sources: list[dict],
) -> tuple[str, list[dict], dict]:
    result = chat(
        session_id,
        question,
        answer_length,
        allow_web_search=allow_web_search,
        collection_name=collection_name,
    )
    answer = str(result.get("answer") or "").strip()
    if not answer:
        raise ApiClientError("Backend returned an empty answer.")
    recovered_sources = _answer_references(_payload_sources(result, sources))
    recovered_meta = normalize_agentic_metadata(result, meta)
    recovered_meta["streaming"] = False
    recovered_meta["response_mode"] = "standard_fallback"
    return answer, recovered_sources, recovered_meta


def _trace_items(meta: dict) -> list[str]:
    items = []
    if not meta:
        return items
    for key in ("search_type", "retrieval_mode", "confidence_level", "retrieved_docs_count"):
        value = meta.get(key)
        if value not in (None, ""):
            items.append(f"{key.replace('_', ' ')}: {value}")
    for step in _as_list(meta.get("trace_steps")):
        if isinstance(step, dict):
            label = step.get("message") or step.get("name") or step.get("step") or step.get("node") or step.get("type") or step.get("status")
            if label:
                items.append(str(label))
        elif step:
            items.append(str(step))
    return items


def _render_agent_trace(meta: dict) -> None:
    items = _trace_items(meta or {})
    if not items:
        return
    chips = "".join(f'<span class="chat-page-trace-chip">{html.escape(item)}</span>' for item in items[:6])
    st.markdown(f'<div class="chat-page-trace-row">{chips}</div>', unsafe_allow_html=True)
    if len(items) > 6:
        with st.expander(f"Show full trace ({len(items)} steps)", expanded=False):
            for item in items:
                st.caption(item)


def _render_message_references(message: dict) -> None:
    if message.get("role") != "assistant":
        return

    sources = _message_sources(message)
    if not sources:
        st.caption("No source references returned.")
        return
    sources = _answer_references(sources)

    for index, source in enumerate(sources, start=1):
        title = _source_title(source, index)
        score = _source_score(source)
        with st.expander(_reference_label(source, index), expanded=False):
            st.caption(f"Source: {title}")
            if score:
                st.caption(f"Score: {score}")
            content = _source_content(source)
            st.write(content if content else "No full chunk text returned.")

    with st.expander(f"Show all references ({len(sources)})", expanded=False):
        for index, source in enumerate(sources, start=1):
            title = _source_title(source, index)
            score = _source_score(source)
            st.markdown(f"**{_reference_label(source, index)}**")
            st.caption(f"Source: {title}")
            if score:
                st.caption(f"Score: {score}")
            content = _source_content(source)
            st.write(content if content else "No full chunk text returned.")
            if index < len(sources):
                st.divider()


def _active_collection_name() -> str:
    return _active_display_collection() or "None"


def _source_identity(source: dict, index: int) -> str:
    metadata = source.get("metadata", {}) or {}
    raw = "|".join(
        [
            _source_value(source, metadata, "chunk_id", fallback=""),
            _source_value(source, metadata, "chunk_index", fallback=""),
            _source_preview(source)[:100],
            str(index),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:10]


def _safe_key_part(value: str, length: int = 8) -> str:
    return hashlib.md5(str(value).encode("utf-8", errors="ignore")).hexdigest()[:length]


def _reference_item_key(panel_key: str, index: int, source_key: str) -> str:
    return f"{panel_key}_{index}_{_safe_key_part(source_key)}"


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    compact_sources = []
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        metadata = source.get("metadata", {}) or {}
        key = (
            _source_value(source, metadata, "chunk_id", "chunk_index", fallback=""),
            _source_preview(source)[:100],
        )
        if key in seen:
            continue
        seen.add(key)
        compact_sources.append(source)
    return compact_sources


def _answer_references(sources: list[dict]) -> list[dict]:
    document_sources, web_sources = _group_sources_by_type(_dedupe_sources(sources))
    return document_sources[:MAX_REFERENCES_PER_ANSWER] + web_sources[:MAX_REFERENCES_PER_ANSWER]


def _is_web_source(source: dict) -> bool:
    if not isinstance(source, dict):
        return False

    metadata = source.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    direct_markers = (
        source.get("source_type"),
        source.get("type"),
        source.get("retrieval_type"),
        metadata.get("source_type"),
    )
    if any(str(value or "").lower() == "web" for value in direct_markers):
        return True

    source_marker = str(source.get("source") or metadata.get("source") or "").lower()
    if source_marker == "web_search":
        return True

    has_url = bool(source.get("url") or source.get("link") or metadata.get("url") or metadata.get("link"))
    has_file_name = bool(source.get("file_name") or metadata.get("file_name"))
    return has_url and not has_file_name


def _group_sources_by_type(sources: list[dict]) -> tuple[list[dict], list[dict]]:
    document_sources = []
    web_sources = []
    for source in sources:
        if _is_web_source(source):
            web_sources.append(source)
        else:
            document_sources.append(source)
    return document_sources, web_sources


def _drawer_references(references: list[dict]) -> list[dict]:
    drawer_sources = []
    history = st.session_state.get("chat_history") or st.session_state.get("messages") or []
    for message in history:
        if message.get("role") == "assistant":
            drawer_sources.extend(_answer_references(_message_sources(message)))
    return drawer_sources if drawer_sources else _answer_references(references)


def _reference_context_state(sources: list[dict], key_prefix: str = "refs") -> tuple[list[dict], list[str], list[str]]:
    compact_sources = [source for source in sources if isinstance(source, dict)]
    panel_id = st.session_state.get("active_collection") or st.session_state.get("collection_name") or "default"
    panel_key = f"{_safe_key_part(panel_id)}_{_safe_key_part(key_prefix)}"
    source_keys = [_source_identity(source, index) for index, source in enumerate(compact_sources, start=1)]
    item_keys = [
        _reference_item_key(panel_key, index, source_key)
        for index, source_key in enumerate(source_keys, start=1)
    ]
    return compact_sources, source_keys, item_keys


def _render_reference_context(sources: list[dict], key_prefix: str = "refs") -> None:
    drawer_html = [
        '<div class="refs-drawer" style="height:auto !important; min-height:0 !important; max-height:calc(100vh - 210px) !important; overflow-y:auto !important; overflow-x:hidden !important;">',
        '<div class="refs-drawer-header">',
        '<h2 class="refs-drawer-title">Reference Context</h2>',
        '<span class="refs-drawer-close-space"></span>',
        "</div>",
        f'<div class="source-collection-line" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:0.78rem; line-height:1.25; margin:0.15rem 0 0.45rem 0;"><strong>Collection:</strong> {html.escape(_active_collection_name())}</div>',
    ]

    if not sources:
        drawer_html.append('<div class="refs-empty">No source references returned.</div>')
        drawer_html.append("</div>")
        st.markdown("".join(drawer_html), unsafe_allow_html=True)
        return

    compact_sources, source_keys, item_keys = _reference_context_state(sources, key_prefix=key_prefix)
    if not compact_sources:
        drawer_html.append('<div class="refs-empty">No source references returned.</div>')
        drawer_html.append("</div>")
        st.markdown("".join(drawer_html), unsafe_allow_html=True)
        return

    document_sources, web_sources = _group_sources_by_type(compact_sources)
    accordion_name = html.escape(f"{key_prefix}_reference_accordion", quote=True)

    def append_source_group(title: str, grouped_sources: list[dict], start_index: int) -> int:
        if not grouped_sources:
            return start_index
        drawer_html.append(f'<div class="ref-group-title" style="margin:0.45rem 0 0.32rem 0; font-size:0.78rem; line-height:1.2;">{html.escape(title)}</div>')
        drawer_html.append('<div class="refs-chip-row" style="display:flex; flex-direction:column; align-items:flex-start; gap:0.32rem; margin:0 0 0.45rem 0;">')
        current_index = start_index
        for source in grouped_sources:
            append_source_detail(source, current_index)
            current_index += 1
        drawer_html.append("</div>")
        return current_index

    def append_source_detail(source: dict, index: int) -> None:
        metadata = source.get("metadata", {}) or {}
        is_web = _is_web_source(source)
        chunk_id = _source_value(source, metadata, "chunk_id", "chunk_index", fallback=f"Chunk {index}")
        page_number = _source_value(source, metadata, "page_number", "page", fallback="n/a")
        url = _source_value(source, metadata, "url", fallback="")
        score = _source_score(source)
        file_label = url if is_web and url else _source_title(source, index)
        meta_rows = [
            ("Ref", index),
            ("File", file_label),
            ("Chunk", "web" if is_web else chunk_id),
            ("Page", "n/a" if is_web else page_number),
            ("Score", score or "n/a"),
        ]
        meta_chips = "".join(
            f'<span style="display:inline-flex; gap:0.24rem; align-items:center; padding:0.2rem 0.42rem; border:1px solid #e2e8f0; border-radius:999px; background:#ffffff; font-size:0.72rem; line-height:1.15;"><strong style="color:#64748b;">{html.escape(str(label))}</strong><span style="color:#172033; overflow-wrap:anywhere;">{html.escape(str(value))}</span></span>'
            for label, value in meta_rows
        )
        label = _reference_label(source, index)
        if ": " in label:
            ref_badge, source_label = label.split(": ", 1)
        else:
            ref_badge, source_label = f"Ref {index}", label
        drawer_html.append(
            f'<details class="refs-chip-detail" name="{accordion_name}" style="display:block; width:fit-content; max-width:100%; margin:0;">'
            '<summary class="refs-chip" style="display:flex; align-items:center; gap:0.38rem; max-width:100%; padding:0.36rem 0.5rem; border:1px solid #dbe3ef; border-radius:9px; background:#f8fafc; color:#172033; cursor:pointer; list-style:none;">'
            f'<span style="flex:0 0 auto; font-size:0.68rem; font-weight:800; color:#475569; background:#ffffff; border:1px solid #e2e8f0; border-radius:999px; padding:0.13rem 0.34rem; line-height:1.1;">{html.escape(ref_badge)}</span>'
            f'<span style="min-width:0; max-width:15rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:0.76rem; font-weight:720; line-height:1.2;">{html.escape(source_label)}</span>'
            '</summary>'
            '<div class="source-detail-card ref-chunk-card" style="margin-top:0.28rem; padding:0.5rem 0.56rem; border:1px solid #e2e8f0; border-radius:9px; background:#ffffff;">'
            f'<div class="ref-meta-line" style="display:flex; flex-wrap:wrap; gap:0.34rem; margin:0 0 0.48rem 0;">{meta_chips}</div>'
            f'<div class="source-scroll-text" style="margin:0; color:#334155; font-size:0.8rem; line-height:1.45; white-space:normal; overflow-wrap:anywhere;">{html.escape(_source_content(source) or "No full chunk text returned.")}</div>'
            "</div></details>"
        )

    next_index = append_source_group("Document sources", document_sources, 1)
    append_source_group("Web search sources", web_sources, next_index)
    drawer_html.append("</div>")
    st.markdown("".join(drawer_html), unsafe_allow_html=True)


def init_ui_state() -> None:
    if "refs_panel_open" not in st.session_state:
        st.session_state.refs_panel_open = False
    st.session_state.setdefault("chat_web_search_enabled", False)
    if "chat_right_drawer_collapsed" not in st.session_state or not st.session_state.get("chat_right_drawer_defaulted_v3"):
        st.session_state.chat_right_drawer_collapsed = True
        st.session_state.chat_right_drawer_defaulted_v3 = True


def toggle_refs_panel() -> None:
    st.session_state.refs_panel_open = not bool(st.session_state.get("refs_panel_open", False))


def close_refs_panel() -> None:
    st.session_state.refs_panel_open = False


def toggle_right_drawer() -> None:
    st.session_state.chat_right_drawer_collapsed = not bool(
        st.session_state.get("chat_right_drawer_collapsed", False)
    )


def render_refs_toggle_button(key: str = "refs_panel_toggle") -> None:
    is_open = bool(st.session_state.get("refs_panel_open", False))
    label = "Hide Sources" if is_open else "Sources"
    help_text = "Hide references" if is_open else "Show references"
    if st.button(label, key=key, help=help_text):
        toggle_refs_panel()
        st.rerun()


# def render_header_toolbar() -> None:
#     st.markdown(
#         """
#         <style>
#         .app-header.chat-page-header {
#             padding: 8px 0 6px 0 !important;
#             margin-bottom: 4px !important;
#         }
#         .app-title-block {
#             margin: 0 !important;
#         }
#         .app-title-block h1 {
#             font-size: 1.2rem !important;
#             margin: 0 !important;
#             font-weight: 800 !important;
#             line-height: 1.2 !important;
#         }
#         .app-title-block p {
#             font-size: 0.8rem !important;
#             margin: 2px 0 0 0 !important;
#             color: #9ca3af !important;
#         }
#         </style>
#         <div class=" ">
#           <div class="">
#             <h3>Chat with Your Documents</h3>
#             <p>Ask questions about your selected collection.</p>
#           </div>
#         </div>
#         """,
#         unsafe_allow_html=True,
#     )

def render_header_toolbar() -> None:
    st.markdown(
        """
        <div class="chat-header-shell"><h4>Chat Documents </h4>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_references_drawer(references: list[dict], key_prefix: str = "refs") -> None:
    if not st.session_state.get("refs_panel_open", False):
        return
    st.markdown('<span class="refs-drawer-close-anchor"></span>', unsafe_allow_html=True)
    if st.button("x", key=f"{key_prefix}_close_button", help="Close references"):
        close_refs_panel()
        st.rerun()
    _render_reference_context(_drawer_references(references), key_prefix=key_prefix)


def render_chat_layout():
    collapsed = bool(st.session_state.get("chat_right_drawer_collapsed", False))
    right_weight = 0.08 if collapsed else 0.24
    center_col, right_col = st.columns([1, right_weight], gap="medium", vertical_alignment="top")

    with right_col:
        _render_right_workspace_panel()

    return center_col, right_col

def _render_right_workspace_panel() -> None:
    collapsed = bool(st.session_state.get("chat_right_drawer_collapsed", False))
    state_class = "is-collapsed" if collapsed else "is-expanded"

    with st.container(key="chat_right_panel"):
        st.markdown(
            f'<span class="chat-right-panel-state {state_class}" aria-hidden="true"></span>',
            unsafe_allow_html=True,
        )
        if not collapsed:
            st.markdown(
                """
                <style>
                html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) {
                    align-content: start !important;
                    grid-template-rows: auto auto auto !important;
                    height: auto !important;
                    min-height: 0 !important;
                }
                html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) > [data-testid="stElementContainer"]:has(.refs-drawer) {
                    align-self: start !important;
                    grid-column: 1 / -1 !important;
                    grid-row: 3 !important;
                    margin: 0 !important;
                    min-height: 0 !important;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div class="references-panel{" collapsed" if collapsed else ""}">',
            unsafe_allow_html=True,
        )

        header_col, toggle_col = st.columns([0.82, 0.18], gap="small")
        with header_col:
            st.markdown(
                """
                <div class="references-header">
                  <div class="references-title-row">
                    <strong>References</strong>
                    <span>Sources and PDF export</span>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with toggle_col:
            toggle_label = chr(0x25B6) if collapsed else chr(0x25C0)
            if st.button(toggle_label, key="chat_right_drawer_toggle", help="Toggle references panel", use_container_width=True):
                toggle_right_drawer()
                st.rerun()

        if collapsed:
            st.markdown('</div>', unsafe_allow_html=True)
            return

        st.markdown('<div class="references-panel-body">', unsafe_allow_html=True)

        _render_export_popover()

        st.markdown('<div class="references-actions">', unsafe_allow_html=True)
        render_refs_toggle_button(key="refs_panel_toggle_right")
        st.markdown('</div>', unsafe_allow_html=True)

        if st.session_state.get("refs_panel_open", False):
            _render_reference_context(
                _drawer_references(st.session_state.get("last_sources", [])),
                key_prefix="refs_right_panel",
            )
        else:
            st.markdown(
                '<div class="references-empty">No source references returned.</div>',
                unsafe_allow_html=True,
            )

        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
            
def _render_export_popover() -> None:
    st.markdown('<span class="export-pdf-anchor"></span>', unsafe_allow_html=True)
    if hasattr(st,"popover"):
        with st.popover("Export", help="Export chat as PDF", key="chat_export_pdf_popover", width="stretch"):
            _render_export_controls()
    else:
        with st.expander("Export", expanded=False):
            _render_export_controls()


def _export_history_with_chunks(history: list[dict]) -> list[dict]:
    export_history = []
    for message in history:
        item = dict(message)
        if item.get("role") == "assistant":
            item["sources"] = _message_sources(item)
        export_history.append(item)
    return export_history


# def _render_export_controls() -> None:
#     history = st.session_state.get("chat_history") or st.session_state.get("messages") or []
#     if not history:
#         st.caption("No chat messages to export.")
#         return
#     pdf_bytes, error = export_chat_to_pdf(
#         _export_history_with_chunks(history),
#         {"active_collection": st.session_state.get("active_collection") or st.session_state.get("collection_name")},
#     )
#     if error:
#         st.warning(error)
#         return
#     st.download_button(
#         "Download PDF",
#         data=pdf_bytes,
#         file_name="agentic_rag_chat.pdf",
#         mime="application/pdf",
#         width="stretch",
#     )
def _export_signature(history: list[dict], active_collection: str) -> str:
    payload = {"history": _export_history_with_chunks(history), "active_collection": active_collection}
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def ensure_pdf_bytes(history: list[dict]) -> tuple[bytes, str | None]:
    active_collection = st.session_state.get("active_collection") or st.session_state.get("collection_name") or ""
    signature = _export_signature(history, active_collection)
    cached_bytes = st.session_state.get("latest_pdf_bytes")
    if (
        st.session_state.get("latest_pdf_signature") == signature
        and isinstance(cached_bytes, bytes)
        and cached_bytes
    ):
        return cached_bytes, None

    pdf_bytes, error = export_chat_to_pdf(
        _export_history_with_chunks(history),
        {"active_collection": active_collection},
    )
    if error:
        st.session_state.latest_pdf_bytes = b""
        st.session_state.latest_pdf_signature = ""
        return b"", error
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
        st.session_state.latest_pdf_bytes = b""
        st.session_state.latest_pdf_signature = ""
        return b"", "PDF export failed: no PDF data generated."
    st.session_state.latest_pdf_bytes = pdf_bytes
    st.session_state.latest_pdf_signature = signature
    return pdf_bytes, None


def _render_export_controls() -> None:
    history = st.session_state.get("chat_history") or st.session_state.get("messages") or []

    if not history:
        st.caption("No chat messages to export.")
        return

    pdf_bytes, error = ensure_pdf_bytes(history)

    if error:
        st.warning(error)
        return

    st.download_button(
        "Download PDF",
        data=pdf_bytes,
        file_name="agentic_rag_chat.pdf",
        mime="application/pdf",
        width="stretch",
    )


def _render_chat_composer(active_collection: str | None) -> tuple[str, bool]:
    suggested_prompt = st.session_state.pop("chat_reuse_query", "")
    pending_question = st.session_state.pop("chat_pending_question", "")
    if st.session_state.get("chat_generating") and not pending_question:
        st.session_state.chat_generating = False
    is_generating = bool(st.session_state.get("chat_generating"))
    selection_matches = _dropdown_matches_active_collection()
    session_ready = bool(active_collection and _active_session_id() and selection_matches)

    prompt = ""
    web_allowed = bool(st.session_state.get("chat_web_search_enabled", False))
    st.markdown('<span class="chat-composer-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    with st.form(key="chat_composer_form", clear_on_submit=True):
        _, input_col, send_col = st.columns([0.07, 1, 0.07], gap="small", vertical_alignment="center")
        with input_col:
            prompt = st.text_input(
                "Ask a question",
                value=suggested_prompt,
                placeholder="Ask a question about your documents...",
                key="chat_composer_prompt",
                disabled=not active_collection or not selection_matches or is_generating,
                label_visibility="collapsed",
            )
        with send_col:
            submitted = st.form_submit_button(
                chr(0x2191),
                disabled=not active_collection or is_generating,
                width="stretch",
            )
    if pending_question:
        return pending_question, bool(st.session_state.get("chat_web_search_enabled", False) and session_ready)
    if not submitted:
        return "", bool(st.session_state.get("chat_web_search_enabled", False) and session_ready)
    if not selection_matches:
        _chat_toast("Please activate the selected collection first.")
        return "", False
    if not prompt:
        return "", bool(web_allowed and session_ready)
    if not active_collection:
        _chat_toast("Please activate a collection first.")
        return "", False
    question, valid = _valid_question(prompt or "", active_collection)
    if not valid:
        _chat_toast("Please enter a valid question.")
        return "", bool(web_allowed and session_ready)
    st.session_state.chat_generating = True
    return question, bool(web_allowed and session_ready)


def _render_web_search_control(active_collection: str | None) -> bool:
    session_ready = bool(active_collection and st.session_state.get("session_id"))
    is_generating = bool(st.session_state.get("chat_generating"))
    st.markdown(
        """
        <style>
        .st-key-chat_web_search_control {
            align-items: center !important;
            display: flex !important;
            justify-content: center !important;
            padding: 0 !important;
        }
        .st-key-chat_web_search_control > [data-testid="stElementContainer"] {
            align-items: center !important;
            display: flex !important;
            height: 100% !important;
            justify-content: center !important;
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
        }
        .st-key-chat_web_search_control [data-testid="stToggle"],
        .st-key-chat_web_search_control [data-testid="stCheckbox"] {
            align-items: center !important;
            display: flex !important;
            height: auto !important;
            justify-content: center !important;
            margin: 0 !important;
            padding: 0 !important;
            width: auto !important;
        }
        .st-key-chat_web_search_control [data-testid="stToggle"] label,
        .st-key-chat_web_search_control [data-testid="stCheckbox"] label {
            align-items: center !important;
            display: flex !important;
            justify-content: center !important;
            margin: 0 !important;
            min-height: 0 !important;
            padding: 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="chat_web_search_control"):
        if hasattr(st, "toggle"):
            allowed = st.toggle(
                "Web Search",
                key="chat_web_search_enabled",
                disabled=not session_ready or is_generating,
                help="Web Search",
                label_visibility="collapsed",
            )
        else:
            allowed = st.checkbox(
                "Web Search",
                key="chat_web_search_enabled",
                disabled=not session_ready or is_generating,
                help="Web Search",
                label_visibility="collapsed",
            )
    return bool(allowed and session_ready)


def inject_custom_css() -> None:
    """Chat styles live in frontend/styles/style.css (FINAL CHAT UI OVERRIDE)."""
    return


st.set_page_config(page_title="Chat | Enterprise RAG", page_icon="R", layout="wide", initial_sidebar_state="expanded")
init_session_state()
init_ui_state()
load_styles()
inject_custom_css()



if not require_login("Chat"):
    st.stop()

require_runtime_credentials("chat")
render_runtime_sidebar()

st.markdown('<div class="rag-page-root chat-page-root" aria-hidden="true"></div>', unsafe_allow_html=True)
workspace_col, source_panel = render_chat_layout()

with workspace_col:
    active_collection = _active_display_collection()
    active_physical_collection = _active_physical_collection()
    chip_class = "ok" if active_physical_collection and _active_session_id() else "warn"
    with st.container(key="chat_top_toolbar"):
        title_col, collection_col, status_col = st.columns(
            [0.26, 0.54, 0.20],
            gap="small",
            vertical_alignment="center",
        )
        with title_col:
            render_header_toolbar()
        with collection_col:
            _render_collection_selector()
        with status_col:
            st.markdown(
                f'<div class="chat-active-pill"><span class="mini-chip {chip_class}">Active: {html.escape(str(active_collection or "None"))}</span></div>',
                unsafe_allow_html=True,
            )

    _render_web_search_control(active_collection if _active_session_id() else None)
    messages_slot = st.container(key="chat_center_panel")

existing_messages = st.session_state.get("chat_history") or st.session_state.get("messages") or []
if existing_messages:
    st.markdown('<span class="chat-has-messages" aria-hidden="true"></span>', unsafe_allow_html=True)

with messages_slot:
    if existing_messages:
        _render_messages(existing_messages)
        if st.session_state.pop("chat_scroll_after_rerun", False):
            _render_chat_autoscroll()
    else:
        st.markdown(
            """
            <div class="chat-empty-state">
              <strong> Ready for your documents </strong>
            </div>
            """,
            unsafe_allow_html=True,
        )

    live_response_slot = st.container(key="chat_live_response_slot")
    _render_chat_bottom_spacer()
    question, manual_web_search_allowed = _render_chat_composer(active_collection if _active_session_id() else None)

approved_web_search = None
question = approved_web_search.get("question") if approved_web_search else question
allow_web_search = bool(approved_web_search) or manual_web_search_allowed

if question:
    active_collection = _active_display_collection()
    active_physical_collection = _active_physical_collection()
    active_session_id = _active_session_id()
    if not _dropdown_matches_active_collection():
        _chat_toast("Please activate the selected collection first.")
        try:
            st.rerun()
        finally:
            st.session_state.chat_generating = False
    if not active_physical_collection or not active_session_id:
        _chat_toast("Please activate a collection first.")
        try:
            st.rerun()
        finally:
            st.session_state.chat_generating = False

    st.session_state.active_collection = active_collection or active_physical_collection
    st.session_state.active_collection_display_name = active_collection or active_physical_collection
    st.session_state.collection_name = active_physical_collection
    st.session_state.selected_collection = active_physical_collection
    st.session_state.attached_collection = active_physical_collection
    st.session_state.active_collection_name = active_physical_collection
    st.session_state.session_id = active_session_id
    st.session_state.active_session_id = active_session_id
    session_ready_for_request = bool(active_physical_collection and active_session_id)
    allow_web_search = bool(
        (bool(approved_web_search) or st.session_state.get("chat_web_search_enabled", False))
        and session_ready_for_request
    )
    server_api_config = st.session_state.get("server_api_config") or {}
    openai_requested = bool(st.session_state.get(USE_OPENAI_KEY))
    runtime_openai_active = bool(openai_requested and get_secret_value("OPENAI_API_KEY"))
    requested_llm_provider = "openai" if runtime_openai_active else (
        server_api_config.get("effective_llm_provider") or server_api_config.get("llm_provider")
    )
    logger.info(
        "Chat payload collection=%s session_id=%s dropdown_collection=%s active_collection=%s",
        active_physical_collection,
        active_session_id,
        _dropdown_collection() or "none",
        active_physical_collection,
    )

    user_message = {"role": "user", "content": question}
    st.session_state.chat_history.append(user_message)
    st.session_state.messages = st.session_state.chat_history

    with live_response_slot:
        render_message_card(
            "user",
            question,
            key=f"chat_live_user_{len(st.session_state.chat_history)}",
        )
        _render_chat_bottom_spacer()
        _render_chat_autoscroll()

    answer_parts = []
    sources = []
    final_answer = ""
    stream_completed = False
    answer_length = get_answer_length_instruction()
    meta = {
        "streaming": True,
        "response_mode": "streaming",
        "trace_steps": [],
        "allow_web_search": allow_web_search,
        "web_search_requested": allow_web_search,
        "openai_requested": openai_requested,
        "runtime_openai_active": runtime_openai_active,
        "llm_provider": requested_llm_provider,
        "llm_model": server_api_config.get("llm_model"),
    }

    with live_response_slot:
        placeholder = st.empty()
        progress = st.empty()
        try:
            progress.markdown('<div class="stream-status">Searching selected collection...</div>', unsafe_allow_html=True)
            for event, payload in chat_stream(
                active_session_id,
                question,
                answer_length,
                allow_web_search=allow_web_search,
                collection_name=active_physical_collection,
            ):
                if event == "sources":
                    sources = _answer_references(_payload_sources(payload, []))
                    st.session_state.last_sources = sources
                elif event == "token":
                    answer_parts.append(payload.get("token", ""))
                    placeholder.markdown(
                        _bubble_html("".join(answer_parts), "assistant", streaming=True),
                        unsafe_allow_html=True,
                    )
                    time.sleep(0.008)
                elif event == "done":
                    final_answer = payload.get("answer") or "".join(answer_parts)
                    sources = _answer_references(_payload_sources(payload, sources))
                    meta = normalize_agentic_metadata(payload, meta)
                    stream_completed = True
                elif event == "trace":
                    meta = normalize_agentic_metadata(
                        {"trace_steps": [*meta.get("trace_steps", []), payload]},
                        meta,
                    )
                elif event == "error":
                    raise ApiClientError(payload.get("message") or "Streaming chat failed.")

            if not stream_completed or not final_answer.strip():
                raise ApiClientError("Streaming response ended before a complete answer was returned.")
        except (ApiClientDisconnect, asyncio.CancelledError) as exc:
            logger.warning("Chat streaming stopped after client disconnect: %s", exc)
            progress.empty()
            placeholder.empty()
            st.rerun()
        except Exception:
            progress.markdown('<div class="stream-status">Retrying with standard response mode...</div>', unsafe_allow_html=True)
            try:
                final_answer, sources, meta = _recover_non_streaming_answer(
                    active_session_id,
                    question,
                    answer_length,
                    allow_web_search,
                    active_physical_collection,
                    meta,
                    sources,
                )
            except ApiClientError as exc:
                progress.empty()
                placeholder.empty()
                st.error(f"Chat failed: {str(exc)}")
                st.rerun()
        finally:
            st.session_state.chat_generating = False

        try:
            progress.empty()
            final_answer = final_answer.strip()
            if final_answer:
                placeholder.empty()
                render_message_card("assistant", final_answer, key=f"chat_live_assistant_{len(st.session_state.chat_history)}", meta=meta)
                assistant_message = {"role": "assistant", "content": final_answer, "sources": sources, "meta": meta}
                st.session_state.chat_history.append(assistant_message)
                st.session_state.messages = st.session_state.chat_history
                st.session_state.last_sources = sources
                st.session_state.last_meta = meta
                fallback_warning = str(meta.get("llm_fallback_warning") or "")
                st.session_state.llm_fallback_warning = fallback_warning
                _save_query_log(question, final_answer, sources, meta)
                st.session_state.chat_scroll_after_rerun = True
                _render_chat_bottom_spacer()
                _render_chat_autoscroll()
            
            st.rerun()
        finally:
            st.session_state.chat_generating = False
