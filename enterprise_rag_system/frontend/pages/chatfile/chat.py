import html

import hashlib
import json
import logging
import math
import re
import sys

import asyncio
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
from components.runtime_secrets import get_secret_value, require_runtime_credentials
from services.api_client import ApiClientError, cached_list_collections, chat, chat_stream, select_collection


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


def _agentic_caption(meta: dict) -> str:
    parts = []
    search_type = meta.get("search_type")
    retrieval_mode = meta.get("retrieval_mode")
    if search_type:
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
    if meta.get("web_search_eligible") is False:
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
    if (meta.get("web_search_used") is True or str(search_type) == "web_search") and meta.get("web_results_count") is not None:
        parts.append(f"{meta['web_results_count']} web results")
    if meta.get("confidence_level"):
        parts.append(f"{meta['confidence_level']} confidence")
    if retrieval_mode:
        parts.append(str(retrieval_mode))
    retriever = meta.get("retriever") or meta.get("retriever_info")
    if retriever:
        parts.append(str(retriever))
    trace_steps = meta.get("trace_steps") or []
    if meta.get("web_search_requires_approval"):
        parts.append("web search available")
    elif not meta.get("web_search_used") and any(
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
        "web_search_available": ("web_search_available",),
        "web_search_requires_approval": ("web_search_requires_approval",),
        "web_search_eligible": ("web_search_eligible",),
        "collection_relevance": ("collection_relevance",),
        "trace_steps": ("trace_steps",),
    }
    for target, keys in aliases.items():
        for key in keys:
            if key in payload and payload[key] is not None:
                result[target] = payload[key]
                break
    return result


def _save_query_log(question: str, answer: str, sources: list, meta: dict) -> None:
    logs = st.session_state.setdefault("query_logs", [])
    log_id = f"chat_{len(logs) + 1}"
    logs.append(
        {
            "id": log_id,
            "title": question[:45] + ("..." if len(question) > 45 else ""),
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


def _attach_chat_collection(selected: dict) -> bool:
    name = _collection_name(selected)
    display_name = _collection_display_name(selected) or name
    try:
        attached = select_collection(
            name,
            selected.get("embedding_provider") or st.session_state.get("embedding_provider", "huggingface"),
        )
        session_id = attached.get("session_id")
        collection_name = attached.get("collection_name") or name
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
        _activation_toast("Collection activated", "success")
        return True
    except ApiClientError as exc:
        st.session_state.attach_status = "failed"
        st.session_state.last_attach_error = str(exc).replace("Collection selection failed:", "").strip()
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
        else:
            _activation_toast(f"Could not activate collection: {st.session_state.last_attach_error}", "warning")
        return False


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
        select_col, button_col = st.columns([1, 0.3], gap="small")
        with select_col:
            selected = st.selectbox(
                "Collection",
                collections,
                index=active_index,
                format_func=_collection_label,
                label_visibility="collapsed",
                key="chat_collection_selector",
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
    st.markdown(
        '<span class="chat-scroll-anchor"></span>'
        '<button class="chat-scroll-focus" type="button" tabindex="-1" autofocus aria-label="Latest message"></button>',
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


def render_message_card(role: str, content: str, key: str, meta: dict | None = None) -> None:
    bubble_class = "user" if role == "user" else "assistant"
    component_id = "chat_msg_" + re.sub(r"[^a-zA-Z0-9_-]+", "_", key)
    body = _message_content_html(content or "").strip()
    caption = _agentic_caption(meta or {}) if role == "assistant" else ""
    caption_html = _caption_chips_html(caption)
    align = "flex-end" if bubble_class == "user" else "flex-start"
    max_width = "70%" if bubble_class == "user" else "82%"
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
          max-width: {max_width};
          border-radius: {radius};
          border: 1px solid {border};
          background: {background};
          color: {color};
          padding: 7px 34px 7px 11px;
          box-shadow: {shadow};
          overflow-wrap: anywhere;
          font-size: 13px;
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
      <div id="{component_id}" class="message-row">
        <div class="bubble">{body}</div>
        {caption_html}
      </div>
    """
    render_copyable_html(component_html, height=_message_component_height(content, role, meta))
    _render_inline_copy_action(content or "", key, bubble_class)


def _render_messages(messages: list[dict]) -> None:
    for message_index, message in enumerate(messages):
        role = message.get("role", "assistant")
        if role in ("user", "assistant"):
            render_message_card(
                role,
                message.get("content", ""),
                key=f"chat_message_{message_index}_{role}",
                meta=message.get("meta", {}),
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
    return f"Ref {index} � {keyword}"


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
        '<input id="refsDrawerCloseToggle" class="refs-drawer-close-toggle" type="checkbox">',
        '<div class="refs-drawer">',
        '<div class="refs-drawer-header">',
        '<h2 class="refs-drawer-title">Reference Context</h2>',
        '<span class="refs-drawer-close-space"></span>',
        "</div>",
        f'<div class="source-collection-line"><strong>Collection:</strong> {html.escape(_active_collection_name())}</div>',
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

    def append_source_group(title: str, grouped_sources: list[dict], start_index: int) -> int:
        if not grouped_sources:
            return start_index
        drawer_html.append(f'<div class="ref-group-title">{html.escape(title)}</div>')
        drawer_html.append('<div class="refs-chip-row">')
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
        details = [f"Ref {index}"]
        if is_web:
            details.append("Type: web search")
            if url:
                details.append(f"URL: {url}")
        else:
            details.extend([f"Chunk: {chunk_id}", f"Page: {page_number}"])
        if score:
            details.append(f"Score: {score}")
        drawer_html.append(
            '<details class="refs-chip-detail">'
            f'<summary class="refs-chip">{html.escape(_reference_label(source, index))}</summary>'
            '<div class="source-detail-card ref-chunk-card">'
            f'<div class="ref-meta-line">{html.escape(" | ".join(details))}</div>'
            f'<div class="source-scroll-text">{html.escape(_source_content(source) or "No full chunk text returned.")}</div>'
            "</div></details>"
        )

    next_index = append_source_group("Document sources", document_sources, 1)
    append_source_group("Web search sources", web_sources, next_index)
    drawer_html.append("</div>")
    st.markdown("".join(drawer_html), unsafe_allow_html=True)


def init_ui_state() -> None:
    if "refs_panel_open" not in st.session_state:
        st.session_state.refs_panel_open = False
    if "allow_web_search" not in st.session_state:
        st.session_state.allow_web_search = False
    if "chat_right_drawer_collapsed" not in st.session_state or not st.session_state.get("chat_right_drawer_defaulted_v2"):
        st.session_state.chat_right_drawer_collapsed = False
        st.session_state.chat_right_drawer_defaulted_v2 = True


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
#             <h2>Chat with Your Documents</h2>
#             <p>Ask questions about your selected collection.</p>
#           </div>
#         </div>
#         """,
#         unsafe_allow_html=True,
#     )

def render_header_toolbar() -> None:
    st.markdown(
        """
        <div class="chat-header-shell">
          <div class="chat-header-inner">
            <div>
              <h2>Chat with Your Documents</h2>
              <p>Ask questions from the active knowledge collection.</p>
            </div>
          </div>
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
    center_col, right_col = st.columns([0.78, 0.22], gap="medium", vertical_alignment="top")

    with right_col:
        _render_right_workspace_panel()

    return center_col, right_col

def _render_right_workspace_panel() -> None:
    with st.container(key="chat_right_panel"):
        st.markdown(
            """
            <div class="simple-reference-panel">
                <h3>References</h3>
                <p>Sources and PDF export</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _render_export_popover()

        if st.button("Sources", key="refs_panel_toggle_right_simple", width="stretch"):
            toggle_refs_panel()
            st.rerun()

        if st.session_state.get("refs_panel_open", False):
            _render_reference_context(
                _drawer_references(st.session_state.get("last_sources", [])),
                key_prefix="refs_right_panel",
            )
        else:
            st.info("No source references returned.")
            
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
    session_ready = bool(active_collection and st.session_state.get("session_id"))

    prompt = ""
    with st.form(key="chat_composer_form", clear_on_submit=True):
        web_col, input_col, send_col = st.columns([0.04, 1, 0.05], gap="small", vertical_alignment="center")
        with web_col:
            if hasattr(st, "toggle"):
                web_allowed = st.toggle(
                    "Web search",
                    key="allow_web_search",
                    disabled=not session_ready or is_generating,
                    label_visibility="collapsed",
                )
            else:
                web_allowed = st.checkbox(
                    "Web search",
                    key="allow_web_search",
                    disabled=not session_ready or is_generating,
                    label_visibility="collapsed",
                )
        with input_col:
            prompt = st.text_input(
                "Ask a question",
                value=suggested_prompt,
                placeholder="Ask a question about your documents...",
                key="chat_composer_prompt",
                disabled=not active_collection or is_generating,
                label_visibility="collapsed",
            )
        with send_col:
            submitted = st.form_submit_button(
                "↑",
                disabled=not active_collection or is_generating,
                width="stretch",
            )
    if pending_question:
        return pending_question, bool(st.session_state.get("allow_web_search") and session_ready)
    if not submitted:
        return "", bool(st.session_state.get("allow_web_search") and session_ready)
    if not prompt:
        return "", bool(web_allowed and session_ready)
    if not active_collection:
        _chat_toast("Please activate a collection first.")
        return "", False
    question, valid = _valid_question(prompt or "", active_collection)
    if not valid:
        _chat_toast("Please enter a valid question.")
        return "", bool(web_allowed and session_ready)
    st.session_state.chat_pending_question = question
    st.session_state.chat_generating = True
    st.rerun()
    return "", bool(web_allowed and session_ready)


def _render_web_search_control(active_collection: str | None) -> bool:
    session_ready = bool(active_collection and st.session_state.get("session_id"))
    with st.container(key="chat_web_search_control"):
        allowed = st.checkbox(
            "Web",
            key="allow_web_search",
            disabled=not session_ready,
        )
    return bool(allowed and session_ready)


def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        .stApp:has(.chat-page-root) {
            --right-panel-width: 320px;
            --chat-surface: #f7f7f7;
            background: var(--chat-surface) !important;
        }

        /* Structural Grid */
        .stApp:has(.chat-page-root) .block-container {
            max-width: 100% !important;
            padding: 0 !important;
            height: 100vh !important;
            overflow: hidden !important;
            display: flex !important;
            flex-direction: column !important;
        }

        /* Main Grid with CSS Variable */
        .chat-main-grid {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) var(--right-panel-width) !important;
            width: 100% !important;
            min-width: 0 !important;
            gap: 0 !important;
            height: calc(100vh - 150px) !important;
            align-items: stretch !important;
        }

        .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_center_panel) {
            display: contents !important;
        }

        .stApp:has(.chat-page-root) [data-testid="column"]:has(.st-key-chat_center_panel) {
            width: 100% !important;
            min-width: 0 !important;
            overflow: hidden !important;
            display: flex !important;
            flex-direction: column !important;
        }

        .stApp:has(.chat-page-root) [data-testid="column"]:has(.st-key-chat_right_panel) {
            width: var(--right-panel-width) !important;
            height: calc(100vh - 150px) !important;
            overflow: hidden !important;
            display: flex !important;
            flex-direction: column !important;
            min-width: 0 !important;
            flex-shrink: 0 !important;
            transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }

        /* Center Panel Workspace */
        .st-key-chat_center_panel {
            width: 100% !important;
            min-width: 0 !important;
            height: 100% !important;
            display: flex !important;
            flex-direction: column !important;
            overflow: hidden !important;
            padding: 12px 14px !important;
            background: #ffffff !important;
            border-radius: 14px 14px 0 0 !important;
            border: 1px solid #e5e7eb !important;
            border-bottom: 0 !important;
            max-width: 980px !important;
            margin: 0 auto !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
            flex-shrink: 0 !important;
            position: sticky !important;
            bottom: 0 !important;
            z-index: 10 !important;
            background: #ffffff !important;
            padding-top: 8px !important;
            padding-bottom: 2px !important;
            border-top: 1px solid #f1f3f6 !important;
            margin-left: -14px !important;
            margin-right: -14px !important;
            padding-left: 14px !important;
            padding-right: 14px !important;
            display: block !important;
            width: 100% !important;
        }

        /* Messages scroll area */
        .st-key-chat_center_panel > [data-testid="stContainer"] {
            flex: 1 1 auto !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            min-height: 0 !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
            margin: 0 !important;
            gap: 6px !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input {
            height: 40px !important;
            font-size: 0.92rem !important;
            padding: 8px 12px !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button {
            height: 40px !important;
            min-width: 40px !important;
            padding: 0 8px !important;
        }

        /* Right Sidebar Container */
        .stApp:has(.chat-page-root) .st-key-chat_right_panel {
            width: var(--right-panel-width) !important;
            height: calc(100vh - 150px) !important;
            background: #ffffff !important;
            border-left: 1px solid #e5e7eb !important;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            padding: 0 !important;
            flex-shrink: 0 !important;
            flex-grow: 0 !important;
            display: flex !important;
            flex-direction: column !important;
        }

        /* Right Panel Content */
        .stApp:has(.chat-page-root) .st-key-chat_right_panel > [data-testid="stContainer"] {
            width: 100% !important;
            padding: 0.5rem !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 0 !important;
            flex: 1 1 auto !important;
        }

        /* Right Panel State Indicator */
        .chat-right-panel-state {
            display: flex !important;
            flex-direction: column !important;
            width: 100% !important;
            height: 100% !important;
            gap: 0 !important;
            padding: 0.5rem 0 !important;
        }

        .chat-right-panel-state.is-expanded {
            padding: 0.75rem !important;
        }

        .chat-right-panel-state.is-collapsed {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            padding: 0.5rem 0 !important;
        }

        /* Hide expanded panel content when collapsed */
        .chat-right-panel-state.is-collapsed .chat-right-panel-head,
        .chat-right-panel-state.is-collapsed .chat-right-sources-action,
        .chat-right-panel-state.is-collapsed .chat-tool-grid,
        .chat-right-panel-state.is-collapsed [data-testid="stExpander"],
        .chat-right-panel-state.is-collapsed .refs-drawer {
            display: none !important;
        }

        /* Show icon rail only when collapsed */
        .chat-right-icon-rail {
            display: flex !important;
            flex-direction: column !important;
            gap: 0.5rem !important;
            align-items: center !important;
            justify-content: center !important;
            width: 100% !important;
            padding: 0.5rem 0 !important;
            flex: 1 1 auto !important;
        }

        .chat-right-panel-state.is-collapsed .chat-right-icon-rail {
            display: flex !important;
        }

        .chat-right-panel-state.is-expanded .chat-right-icon-rail {
            display: none !important;
        }

        .chat-right-icon {
            width: 48px !important;
            height: 48px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 1.25rem !important;
            opacity: 0.6 !important;
            cursor: pointer !important;
            transition: opacity 0.2s ease !important;
            border-radius: 8px !important;
        }

        .chat-right-icon:hover {
            opacity: 1 !important;
        }

        /* Tool Cards */
        .chat-tool-grid {
            display: grid !important;
            grid-template-columns: 1fr 1fr !important;
            gap: 10px !important;
            margin-top: 12px !important;
            padding: 0 !important;
        }

        .chat-tool-card {
            background: #f8fafc !important;
            border: 1px solid #e2e8f0 !important;
            border-radius: 10px !important;
            padding: 10px !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
            min-height: 68px !important;
            transition: all 0.2s ease !important;
            font-size: 0.75rem !important;
        }

        .chat-tool-card span {
            font-size: 1.5rem !important;
            margin-bottom: 4px !important;
        }

        .chat-tool-card strong {
            font-size: 0.7rem !important;
            font-weight: 700 !important;
            line-height: 1.1 !important;
            margin-bottom: 2px !important;
        }

        .chat-tool-card em {
            font-size: 0.65rem !important;
            color: #999 !important;
            font-style: normal !important;
        }

        .chat-tool-card:hover {
            background: #edf2ff !important;
            border-color: #c7d2fe !important;
            transform: translateY(-2px) !important;
        }

        /* Chat Messages */
        .chat-empty-state {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            min-height: 180px !important;
            text-align: center !important;
            color: #9ca3af !important;
            font-size: 0.95rem !important;
        }

        .chat-empty-state strong {
            display: block !important;
            color: #6b7280 !important;
            font-size: 1rem !important;
            margin-bottom: 6px !important;
        }

        .message-row {
            margin-bottom: 0.6rem !important;
            display: flex !important;
        }

        .message-row strong {
            font-weight: 700 !important;
        }

        /* Web Search Toggle */
        .st-key-chat_web_search_control {
            margin: 6px 0 0 0 !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
        }

        .st-key-chat_web_search_control [data-testid="stCheckbox"] {
            background: #f1f3f6 !important;
            padding: 3px 8px !important;
            border-radius: 18px !important;
        }

        /* Compact Chat Controls */
        .st-key-chat_collection_selector {
            margin-bottom: 6px !important;
            padding-bottom: 6px !important;
        }

        .chat-active-pill {
            padding: 0 0 6px 0 !important;
            margin-bottom: 4px !important;
        }

        .mini-chip {
            display: inline-flex !important;
            padding: 4px 8px !important;
            border-radius: 6px !important;
            font-size: 0.75rem !important;
            font-weight: 700 !important;
        }

        /* Global cleanup */
        [data-testid="stHeader"] { display: none !important; }
        [data-testid="stBottom"] { display: none !important; }

        /* Final stable chat layout override: keep the Studio panel in a real column. */
        .stApp:has(.chat-page-root) .block-container {
            max-width: none !important;
            width: 100% !important;
            min-height: 100vh !important;
            padding: 0.75rem 0.95rem 0.75rem 0.95rem !important;
            overflow: hidden !important;
        }

        .stApp:has(.chat-page-root) [data-testid="stVerticalBlock"] {
            gap: 0.55rem !important;
        }

        .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_center_panel) {
            display: flex !important;
            align-items: stretch !important;
            gap: 1rem !important;
            width: 100% !important;
            max-width: 100% !important;
            height: calc(100vh - 158px) !important;
            min-height: 520px !important;
            overflow: hidden !important;
        }

        .stApp:has(.chat-page-root) [data-testid="column"]:has(.st-key-chat_center_panel) {
            flex: 1 1 auto !important;
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
            height: 100% !important;
            overflow: hidden !important;
        }

        .stApp:has(.chat-page-root) [data-testid="column"]:has(.st-key-chat_right_panel) {
            flex: 0 0 var(--right-panel-width) !important;
            width: var(--right-panel-width) !important;
            min-width: var(--right-panel-width) !important;
            max-width: var(--right-panel-width) !important;
            height: 100% !important;
            overflow: hidden !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel {
            width: 100% !important;
            max-width: none !important;
            height: 100% !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0.95rem 1.1rem 0.85rem 1.1rem !important;
            border: 1px solid #e4ecf7 !important;
            border-radius: 18px !important;
            background: #ffffff !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            box-sizing: border-box !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
            position: sticky !important;
            bottom: 0 !important;
            z-index: 30 !important;
            width: min(100%, 980px) !important;
            margin: 1rem auto 0 auto !important;
            padding: 0.45rem !important;
            border: 1px solid #d7e1ef !important;
            border-radius: 24px !important;
            background: #ffffff !important;
            box-shadow: 0 18px 38px rgba(15, 23, 42, 0.12) !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input {
            height: 44px !important;
            border-radius: 16px !important;
            background: #ffffff !important;
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
            caret-color: #2563eb !important;
            box-shadow: none !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input::placeholder {
            color: #94a3b8 !important;
            -webkit-text-fill-color: #94a3b8 !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button {
            width: 44px !important;
            min-width: 44px !important;
            height: 44px !important;
            border-radius: 999px !important;
            background: #111827 !important;
            color: #ffffff !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_right_panel {
            position: static !important;
            width: 100% !important;
            min-width: 0 !important;
            max-width: 100% !important;
            height: 100% !important;
            min-height: 0 !important;
            padding: 0.85rem !important;
            border: 1px solid #dfe8f5 !important;
            border-radius: 18px !important;
            background: #ffffff !important;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08) !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            box-sizing: border-box !important;
        }

        .stApp:has(.chat-page-root) .st-key-chat_right_panel > [data-testid="stVerticalBlock"],
        .stApp:has(.chat-page-root) .st-key-chat_right_panel > [data-testid="stContainer"] {
            width: 100% !important;
            max-width: 100% !important;
            min-width: 0 !important;
        }

        .chat-right-panel-state {
            width: 100% !important;
            min-width: 0 !important;
            overflow: hidden !important;
            box-sizing: border-box !important;
        }

        .chat-right-panel-state.is-collapsed {
            align-items: center !important;
            padding: 0.25rem 0 !important;
        }

        .chat-right-panel-state.is-expanded .chat-right-icon-rail {
            display: none !important;
        }

        .chat-right-panel-state.is-collapsed .chat-right-icon-rail {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 0.6rem !important;
            width: 100% !important;
            padding-top: 0.75rem !important;
        }

        .chat-right-panel-state.is-collapsed .chat-right-panel-head,
        .chat-right-panel-state.is-collapsed .chat-right-sources-action,
        .chat-right-panel-state.is-collapsed .chat-tool-grid,
        .chat-right-panel-state.is-collapsed [data-testid="stPopover"],
        .chat-right-panel-state.is-collapsed .refs-drawer {
            display: none !important;
        }

        .chat-right-icon {
            width: 42px !important;
            height: 42px !important;
            border: 1px solid #dbe5f2 !important;
            border-radius: 14px !important;
            background: #f8fbff !important;
            opacity: 1 !important;
            font-size: 1.05rem !important;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06) !important;
        }

        .chat-tool-grid {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 0.75rem !important;
            width: 100% !important;
            overflow: visible !important;
        }

        .chat-tool-card {
            min-width: 0 !important;
            min-height: 82px !important;
            align-items: flex-start !important;
            text-align: left !important;
        }

        .chat-tool-card strong,
        .chat-tool-card em {
            max-width: 100% !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        .chat-collection-card [data-testid="stSelectbox"] input,
        .chat-collection-card [role="combobox"] input,
        .chat-collection-card [contenteditable="true"] {
            caret-color: transparent !important;
            pointer-events: none !important;
            user-select: none !important;
        }

        .chat-collection-card [data-baseweb="select"],
        .chat-collection-card [role="combobox"] {
            cursor: pointer !important;
            caret-color: transparent !important;
            user-select: none !important;
        }

        @media (max-width: 1100px) {
            .stApp:has(.chat-page-root) {
                --right-panel-width: 72px;
            }

            .chat-right-panel-state .chat-right-panel-head,
            .chat-right-panel-state .chat-right-sources-action,
            .chat-right-panel-state .chat-tool-grid,
            .chat-right-panel-state [data-testid="stPopover"],
            .chat-right-panel-state .refs-drawer {
                display: none !important;
            }

            .chat-right-panel-state .chat-right-icon-rail {
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                gap: 0.6rem !important;
            }
        }

        /* Notebook-style final chat layout: keep composer and right rail visible at every zoom. */
        html body .stApp:has(.chat-page-root) {
            --chat-right-width: var(--right-panel-width, 72px) !important;
        }

        html body .stApp:has(.chat-page-root) .block-container.block-container {
            max-width: none !important;
            width: 100% !important;
            height: 100vh !important;
            min-height: 100vh !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) .chat-collection-card,
        html body .stApp:has(.chat-page-root) .chat-active-pill,
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_collection_selector),
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
            max-width: none !important;
            width: 100% !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
            display: flex !important;
            align-items: stretch !important;
            gap: 1rem !important;
            height: calc(100vh - 166px) !important;
            min-height: 0 !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel) {
            flex: 1 1 auto !important;
            width: auto !important;
            min-width: 0 !important;
            max-width: none !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel) {
            flex: 0 0 var(--chat-right-width) !important;
            width: var(--chat-right-width) !important;
            min-width: var(--chat-right-width) !important;
            max-width: var(--chat-right-width) !important;
            height: 100% !important;
            overflow: hidden !important;
            background: #ffffff !important;
            border: 1px solid #dfe8f5 !important;
            border-radius: 18px !important;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08) !important;
            box-sizing: border-box !important;
            padding: 0.55rem !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel) > div {
            height: 100% !important;
            min-height: 100% !important;
            width: 100% !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel {
            display: flex !important;
            flex-direction: column !important;
            height: 100% !important;
            min-height: 0 !important;
            width: 100% !important;
            max-width: none !important;
            margin: 0 !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            padding: 0.95rem 1.1rem !important;
            border: 1px solid #e4ecf7 !important;
            border-radius: 18px !important;
            background: #ffffff !important;
            box-sizing: border-box !important;
        }

        html body .stApp:has(.chat-page-root) .message-row {
            flex-shrink: 0 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
            position: sticky !important;
            bottom: 0 !important;
            z-index: 50 !important;
            width: min(100%, 980px) !important;
            max-width: 980px !important;
            margin: auto auto 0 auto !important;
            padding: 0.42rem !important;
            background: #ffffff !important;
            border: 1px solid #d5deeb !important;
            border-radius: 24px !important;
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.13) !important;
            flex-shrink: 0 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
            align-items: center !important;
            gap: 0.45rem !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"] {
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            min-width: 5.1rem !important;
            height: 44px !important;
            padding: 0 0.6rem !important;
            border-radius: 999px !important;
            background: #f1f5f9 !important;
            white-space: nowrap !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stTextInput"] input {
            height: 44px !important;
            border-radius: 16px !important;
            background: #ffffff !important;
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
            caret-color: #2563eb !important;
            box-shadow: none !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stTextInput"] input::placeholder {
            color: #64748b !important;
            -webkit-text-fill-color: #64748b !important;
            opacity: 1 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button {
            width: 44px !important;
            min-width: 44px !important;
            height: 44px !important;
            border-radius: 999px !important;
            background: #111827 !important;
            color: #ffffff !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel {
            width: 100% !important;
            max-width: 100% !important;
            height: 100% !important;
            min-height: 100% !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
            border: 0 !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            padding: 0 !important;
            background: transparent !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-collapsed) {
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) .chat-right-icon-rail {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 0.7rem !important;
            width: 100% !important;
            padding-top: 0.25rem !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-collapsed) .chat-right-icon-rail {
            display: flex !important;
            visibility: visible !important;
            opacity: 1 !important;
        }

        html body .stApp:has(.chat-page-root) .chat-right-icon {
            width: 42px !important;
            height: 42px !important;
            border-radius: 14px !important;
            border: 1px solid #dbe5f2 !important;
            background: #f8fbff !important;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06) !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 1.05rem !important;
            opacity: 1 !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-collapsed) .stButton:first-of-type button {
            width: 42px !important;
            min-width: 42px !important;
            height: 42px !important;
            margin: 0 auto 0.7rem auto !important;
            border-radius: 12px !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stColumn"]:has(.st-key-chat_right_panel .chat-right-panel-state.is-collapsed) {
            position: fixed !important;
            right: 1rem !important;
            top: 0.9rem !important;
            width: 72px !important;
            min-width: 72px !important;
            max-width: 72px !important;
            height: calc(100vh - 1.8rem) !important;
            z-index: 80 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) {
            padding: 0.2rem !important;
            overflow-y: auto !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-panel-head {
            margin: 0.55rem 0 0.9rem 0 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-panel-head strong {
            color: #0f172a !important;
            display: block !important;
            font-size: 1.05rem !important;
            line-height: 1.15 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-panel-head span {
            color: #64748b !important;
            display: block !important;
            font-size: 0.78rem !important;
            margin-top: 0.18rem !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-chat_export_pdf_popover button,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopoverButton"] button {
            align-items: center !important;
            background: #ffffff !important;
            border: 1px solid #d8e2ef !important;
            border-radius: 12px !important;
            box-shadow: none !important;
            color: #0f172a !important;
            display: flex !important;
            font-size: 0.92rem !important;
            font-weight: 700 !important;
            height: 42px !important;
            justify-content: center !important;
            margin: 0 0 0.75rem 0 !important;
            min-height: 42px !important;
            width: 100% !important;
            -webkit-text-fill-color: #0f172a !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-chat_export_pdf_popover button:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopoverButton"] button:hover {
            background: #f8fbff !important;
            border-color: #bfdbfe !important;
            color: #1d4ed8 !important;
            -webkit-text-fill-color: #1d4ed8 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-sources-action {
            margin: 0.2rem 0 1rem 0 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-sources-action .stButton > button {
            background: #ffffff !important;
            border: 1px solid #d8e2ef !important;
            border-radius: 12px !important;
            box-shadow: none !important;
            color: #0f172a !important;
            font-size: 0.88rem !important;
            font-weight: 700 !important;
            height: 40px !important;
            min-height: 40px !important;
            padding: 0 0.95rem !important;
            width: auto !important;
            -webkit-text-fill-color: #0f172a !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-sources-action .stButton > button:hover {
            background: #f8fbff !important;
            border-color: #bfdbfe !important;
            color: #1d4ed8 !important;
            -webkit-text-fill-color: #1d4ed8 !important;
        }

        html body .stApp:has(.chat-page-root) .chat-tool-grid {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 0.72rem !important;
            width: 100% !important;
            overflow: visible !important;
        }

        html body .stApp:has(.chat-page-root) .chat-tool-card {
            border-radius: 14px !important;
            box-sizing: border-box !important;
            justify-content: flex-start !important;
            min-height: 86px !important;
            padding: 0.72rem 0.78rem !important;
        }

        html body .stApp:has(.chat-page-root) .chat-tool-card span {
            font-size: 1.15rem !important;
            line-height: 1 !important;
            margin-bottom: 0.38rem !important;
        }

        html body .stApp:has(.chat-page-root) .chat-tool-card strong,
        html body .stApp:has(.chat-page-root) .chat-tool-card em {
            max-width: 100% !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stSelectbox"] input,
        html body .stApp:has(.chat-page-root) .chat-collection-card [role="combobox"] input,
        html body .stApp:has(.chat-page-root) .chat-collection-card [contenteditable="true"] {
            caret-color: transparent !important;
            color: transparent !important;
            opacity: 0 !important;
            pointer-events: none !important;
            user-select: none !important;
            width: 0 !important;
        }

        html body .stApp:has(.chat-page-root) .chat-collection-card [data-baseweb="select"],
        html body .stApp:has(.chat-page-root) .chat-collection-card [role="combobox"] {
            cursor: pointer !important;
            caret-color: transparent !important;
            user-select: none !important;
        }

        /* High-contrast composer colors. Keep this last so global Streamlit button/input
           styling cannot make text/icons blend into the background. */
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
            background: #ffffff !important;
            border-color: #cbd5e1 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stTextInput"],
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stTextInputRootElement"],
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-baseweb="input"],
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-baseweb="base-input"],
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-baseweb="input"] > div {
            background: #ffffff !important;
            border-color: transparent !important;
            box-shadow: none !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stTextInputRootElement"]:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-baseweb="input"]:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stTextInputRootElement"]:focus-within,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-baseweb="input"]:focus-within {
            background: #f8fafc !important;
            border-color: #93c5fd !important;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12) !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] input,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] input:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] input:focus,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] input:active {
            background: transparent !important;
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
            caret-color: #2563eb !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] input::placeholder {
            color: #64748b !important;
            -webkit-text-fill-color: #64748b !important;
            opacity: 1 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"],
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stToggle"],
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"] label,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stToggle"] label,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"] p,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stToggle"] p,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"] span {
            color: #334155 !important;
            -webkit-text-fill-color: #334155 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"],
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stToggle"] {
            width: 52px !important;
            min-width: 52px !important;
            max-width: 52px !important;
            height: 44px !important;
            padding: 0 !important;
            border-radius: 999px !important;
            background: #eef2f7 !important;
            border: 1px solid #d8e2ef !important;
            box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.06) !important;
            transition: background 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"]:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stToggle"]:hover {
            background: #e0f2fe !important;
            border-color: #7dd3fc !important;
            box-shadow: 0 8px 18px rgba(14, 165, 233, 0.18) !important;
            transform: translateY(-1px) !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"] label,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stToggle"] label {
            width: 100% !important;
            height: 100% !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            cursor: pointer !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stCheckbox"] p,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stToggle"] p {
            display: none !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button p,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button span,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button div {
            background: #0f172a !important;
            border-color: #0f172a !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            text-shadow: none !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button:focus-visible {
            background: #2563eb !important;
            border-color: #2563eb !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            box-shadow: 0 12px 26px rgba(37, 99, 235, 0.28) !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button:disabled,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button:disabled p,
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button:disabled span {
            background: #e2e8f0 !important;
            border-color: #e2e8f0 !important;
            color: #475569 !important;
            -webkit-text-fill-color: #475569 !important;
            opacity: 1 !important;
        }

        /* Studio panel controls must stay light; broad chat button rules can otherwise
           turn Export/Sources dark in the expanded right drawer. */
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-chat_export_pdf_popover button,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopover"] button,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopoverButton"] button,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-refs_panel_toggle_right button,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-sources-action button {
            align-items: center !important;
            background: #ffffff !important;
            border: 1px solid #d8e2ef !important;
            border-radius: 12px !important;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06) !important;
            color: #334155 !important;
            display: flex !important;
            font-weight: 700 !important;
            justify-content: center !important;
            min-height: 42px !important;
            text-shadow: none !important;
            width: 100% !important;
            -webkit-text-fill-color: #334155 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-chat_export_pdf_popover button:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopover"] button:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopoverButton"] button:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-refs_panel_toggle_right button:hover,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-sources-action button:hover {
            background: #f8fbff !important;
            border-color: #93c5fd !important;
            box-shadow: 0 10px 24px rgba(37, 99, 235, 0.13) !important;
            color: #1d4ed8 !important;
            -webkit-text-fill-color: #1d4ed8 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-chat_export_pdf_popover button *,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopover"] button *,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) [data-testid="stPopoverButton"] button *,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .st-key-refs_panel_toggle_right button *,
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-sources-action button * {
            background: transparent !important;
            color: inherit !important;
            text-shadow: none !important;
            -webkit-text-fill-color: inherit !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-right-sources-action {
            margin: 0.75rem 0 1rem 0 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-expanded) .chat-tool-grid {
            gap: 0.82rem !important;
            margin-top: 0.75rem !important;
        }

        /* Final right-drawer layout guard: keep the Studio rail/panel inside the
           chat grid so it never overlays Activate, composer, or messages. */
        html body .stApp:has(.chat-page-root):has(.chat-right-panel-state.is-collapsed) {
            --chat-right-width: 72px !important;
        }

        html body .stApp:has(.chat-page-root):has(.chat-right-panel-state.is-expanded) {
            --chat-right-width: 320px !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
            align-items: stretch !important;
            display: flex !important;
            gap: 1rem !important;
            height: calc(100vh - 166px) !important;
            min-height: 480px !important;
            overflow: hidden !important;
            width: 100% !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel) {
            flex: 1 1 auto !important;
            max-width: none !important;
            min-width: 0 !important;
            overflow: hidden !important;
            width: auto !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel),
        html body .stApp:has(.chat-page-root) [data-testid="stColumn"]:has(.st-key-chat_right_panel .chat-right-panel-state.is-collapsed) {
            background: #ffffff !important;
            border: 1px solid #dfe8f5 !important;
            border-radius: 18px !important;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08) !important;
            box-sizing: border-box !important;
            flex: 0 0 var(--chat-right-width) !important;
            height: 100% !important;
            max-width: var(--chat-right-width) !important;
            min-width: var(--chat-right-width) !important;
            overflow: hidden !important;
            padding: 0.55rem !important;
            position: relative !important;
            right: auto !important;
            top: auto !important;
            width: var(--chat-right-width) !important;
            z-index: 3 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel {
            height: 100% !important;
            max-width: 100% !important;
            overflow-x: hidden !important;
            overflow-y: auto !important;
            width: 100% !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-collapsed) {
            align-items: center !important;
            display: flex !important;
            flex-direction: column !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel:has(.chat-right-panel-state.is-collapsed) .chat-right-icon-rail {
            align-items: center !important;
            display: flex !important;
            flex-direction: column !important;
            gap: 0.64rem !important;
            width: 100% !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
            height: calc(100vh - 92px) !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel) > div {
            display: flex !important;
            flex-direction: column !important;
            height: 100% !important;
            min-height: 0 !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel) .chat-collection-card,
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel) .chat-active-pill {
            flex: 0 0 auto !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) .st-key-chat_center_panel {
            flex: 1 1 auto !important;
            height: auto !important;
            min-height: 0 !important;
        }

        /* Final production guard: stable streaming layout + fixed bottom composer. */
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
            height: auto !important;
            min-height: calc(100vh - 148px) !important;
            max-height: calc(100vh - 148px) !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel) > div {
            gap: 0.55rem !important;
            justify-content: flex-start !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel {
            display: flex !important;
            flex: 1 1 auto !important;
            flex-direction: column !important;
            justify-content: flex-start !important;
            min-height: calc(100vh - 250px) !important;
            overflow-x: hidden !important;
            overflow-y: auto !important;
            padding: 0.75rem 0.9rem 0.9rem 0.9rem !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
            bottom: 0 !important;
            margin-top: auto !important;
            position: sticky !important;
            z-index: 25 !important;
        }

        html body .stApp:has(.chat-page-root) .chat-empty-state {
            margin: 0.1rem auto 0.7rem auto !important;
            min-height: 180px !important;
            padding: 1.2rem !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel {
            align-self: stretch !important;
            margin-top: 0 !important;
            padding-top: 0 !important;
            top: 0 !important;
        }

        html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stSelectbox"] input,
        html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stSelectbox"] textarea,
        html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stSelectbox"] [contenteditable="true"],
        html body .stApp:has(.chat-page-root) .chat-collection-card [role="combobox"] input,
        html body .stApp:has(.chat-page-root) .chat-collection-card [role="combobox"] [contenteditable="true"] {
            caret-color: transparent !important;
            pointer-events: none !important;
            user-select: none !important;
        }

        html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stSelectbox"] [role="combobox"],
        html body .stApp:has(.chat-page-root) .chat-collection-card [data-baseweb="select"] {
            cursor: pointer !important;
        }


        /* =========================================================
           DS FINAL PROFESSIONAL CHAT UI OVERRIDE
           Purpose: compact top, stable center chat, no right rail overlap,
           cleaner collection row, readable composer, responsive behavior.
           ========================================================= */
        html body .stApp:has(.chat-page-root) {
            --chat-right-width: 76px !important;
            --right-panel-width: 76px !important;
            background: linear-gradient(180deg, #f8fafc 0%, #eef3f9 100%) !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHeader"],
        html body .stApp:has(.chat-page-root) [data-testid="stToolbar"],
        html body .stApp:has(.chat-page-root) [data-testid="stDecoration"],
        html body .stApp:has(.chat-page-root) [data-testid="stStatusWidget"] {
            display: none !important;
            height: 0 !important;
        }

        html body .stApp:has(.chat-page-root) .block-container.block-container {
            padding: 0.55rem 1rem 0.8rem 1rem !important;
            max-width: 100% !important;
            width: 100% !important;
            height: 100vh !important;
            overflow: hidden !important;
        }

        .chat-header-shell {
            width: 100% !important;
            margin: 0 0 0.55rem 0 !important;
            padding: 0 !important;
            display: flex !important;
            justify-content: flex-start !important;
            align-items: center !important;
        }
        .chat-header-inner {
            width: 100% !important;
            max-width: none !important;
            padding: 0 !important;
            margin: 0 !important;
            text-align: left !important;
        }
        .chat-header-inner h2 {
            margin: 0 !important;
            padding: 0 !important;
            font-size: 1.18rem !important;
            line-height: 1.16 !important;
            font-weight: 850 !important;
            letter-spacing: -0.035em !important;
            color: #0f172a !important;
        }
        .chat-header-inner p {
            margin: 0.14rem 0 0 0 !important;
            padding: 0 !important;
            font-size: 0.83rem !important;
            line-height: 1.2 !important;
            color: #64748b !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
            display: flex !important;
            gap: 0.9rem !important;
            width: 100% !important;
            height: calc(100vh - 76px) !important;
            min-height: 0 !important;
            max-height: calc(100vh - 76px) !important;
            align-items: stretch !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel) {
            flex: 1 1 auto !important;
            min-width: 0 !important;
            width: auto !important;
            max-width: none !important;
            overflow: hidden !important;
        }

        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel) {
            flex: 0 0 var(--chat-right-width) !important;
            width: var(--chat-right-width) !important;
            min-width: var(--chat-right-width) !important;
            max-width: var(--chat-right-width) !important;
            height: 100% !important;
            padding: 0.55rem 0.45rem !important;
            border: 1px solid #dbe7f5 !important;
            border-radius: 20px !important;
            background: rgba(255,255,255,0.92) !important;
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.08) !important;
            overflow: hidden !important;
            box-sizing: border-box !important;
        }

        html body .stApp:has(.chat-page-root):has(.chat-right-panel-state.is-expanded) {
            --chat-right-width: 320px !important;
            --right-panel-width: 320px !important;
        }

        html body .stApp:has(.chat-page-root) .chat-collection-card {
            margin: 0 0 0.35rem 0 !important;
            padding: 0 !important;
        }
        html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stHorizontalBlock"] {
            gap: 0.7rem !important;
            align-items: center !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_collection_selector [data-baseweb="select"] {
            min-height: 46px !important;
            border-radius: 13px !important;
            background: #111827 !important;
            border: 1px solid #1f2937 !important;
            box-shadow: 0 10px 24px rgba(15,23,42,0.08) !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_collection_selector [data-baseweb="select"] * {
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-size: 0.92rem !important;
            font-weight: 650 !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_activate_collection button {
            height: 46px !important;
            border-radius: 13px !important;
            border: 1px solid #cbd8e8 !important;
            background: #ffffff !important;
            color: #0f172a !important;
            font-weight: 800 !important;
            font-size: 0.96rem !important;
            box-shadow: 0 10px 24px rgba(15,23,42,0.05) !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_activate_collection button:hover {
            border-color: #2563eb !important;
            color: #1d4ed8 !important;
            transform: translateY(-1px) !important;
        }

        html body .stApp:has(.chat-page-root) .chat-active-pill {
            margin: 0 0 0.35rem 0 !important;
            padding: 0 !important;
        }
        html body .stApp:has(.chat-page-root) .mini-chip {
            border-radius: 999px !important;
            padding: 0.26rem 0.62rem !important;
            font-size: 0.76rem !important;
            font-weight: 800 !important;
            background: #fff7ed !important;
            border: 1px solid #fed7aa !important;
            color: #c2410c !important;
        }
        html body .stApp:has(.chat-page-root) .mini-chip.ok {
            background: #ecfdf5 !important;
            border-color: #bbf7d0 !important;
            color: #047857 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel {
            height: 100% !important;
            min-height: 0 !important;
            display: flex !important;
            flex-direction: column !important;
            border: 1px solid #dfe8f5 !important;
            border-radius: 20px !important;
            background: rgba(255,255,255,0.94) !important;
            box-shadow: 0 18px 44px rgba(15,23,42,0.07) !important;
            padding: 0.75rem 0.9rem 0.75rem 0.9rem !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
        }

        html body .stApp:has(.chat-page-root) .chat-empty-state {
            flex: 1 1 auto !important;
            min-height: 230px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            flex-direction: column !important;
            text-align: center !important;
            color: #94a3b8 !important;
        }
        html body .stApp:has(.chat-page-root) .chat-empty-state strong {
            color: #64748b !important;
            font-size: 1rem !important;
            font-weight: 800 !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
            margin: auto auto 0 auto !important;
            width: min(100%, 1040px) !important;
            position: sticky !important;
            bottom: 0 !important;
            z-index: 40 !important;
            padding: 0.42rem !important;
            border-radius: 24px !important;
            border: 1px solid #cbd8e8 !important;
            background: #ffffff !important;
            box-shadow: 0 22px 48px rgba(15,23,42,0.12) !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
            gap: 0.5rem !important;
            align-items: center !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input {
            height: 44px !important;
            border: 0 !important;
            border-radius: 18px !important;
            background: #ffffff !important;
            box-shadow: none !important;
            color: #0f172a !important;
            -webkit-text-fill-color: #0f172a !important;
            font-size: 0.94rem !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input::placeholder {
            color: #64748b !important;
            -webkit-text-fill-color: #64748b !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button {
            width: 44px !important;
            min-width: 44px !important;
            height: 44px !important;
            border-radius: 999px !important;
            background: #0f172a !important;
            color: #ffffff !important;
            border: 0 !important;
            font-size: 1.2rem !important;
            box-shadow: 0 10px 24px rgba(15,23,42,0.2) !important;
        }

        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel {
            width: 100% !important;
            height: 100% !important;
            padding: 0 !important;
            background: transparent !important;
            border: 0 !important;
            box-shadow: none !important;
            overflow: hidden auto !important;
        }
        html body .stApp:has(.chat-page-root) .st-key-chat_right_panel .stButton > button {
            border-radius: 14px !important;
            border: 1px solid #dbe7f5 !important;
            background: #111827 !important;
            color: #ffffff !important;
            min-height: 40px !important;
        }
        html body .stApp:has(.chat-page-root) .chat-right-icon-rail {
            gap: 0.56rem !important;
            padding-top: 0.55rem !important;
            align-items: center !important;
        }
        html body .stApp:has(.chat-page-root) .chat-right-icon {
            width: 42px !important;
            height: 42px !important;
            border-radius: 14px !important;
            border: 1px solid #dbe7f5 !important;
            background: linear-gradient(180deg, #ffffff 0%, #f4f8fd 100%) !important;
            box-shadow: 0 8px 18px rgba(15,23,42,0.06) !important;
            font-size: 1.05rem !important;
            opacity: 1 !important;
        }
        html body .stApp:has(.chat-page-root) .chat-right-panel-head {
            padding: 0.2rem 0.1rem 0.75rem 0.1rem !important;
        }
        html body .stApp:has(.chat-page-root) .chat-right-panel-head strong {
            display: block !important;
            color: #0f172a !important;
            font-size: 1rem !important;
            font-weight: 850 !important;
        }
        html body .stApp:has(.chat-page-root) .chat-right-panel-head span {
            display: block !important;
            color: #64748b !important;
            font-size: 0.78rem !important;
            margin-top: 0.12rem !important;
        }
        html body .stApp:has(.chat-page-root) .chat-tool-grid {
            display: grid !important;
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 0.65rem !important;
        }
        html body .stApp:has(.chat-page-root) .chat-tool-card {
            min-height: 78px !important;
            border-radius: 16px !important;
            background: #f8fbff !important;
            border: 1px solid #dbe7f5 !important;
            padding: 0.7rem !important;
            box-shadow: none !important;
        }

        html body .stApp:has(.chat-page-root) .copy-action-label,
        html body .stApp:has(.chat-page-root) .stCodeBlock {
            display: none !important;
        }

        @media (max-width: 900px) {
            html body .stApp:has(.chat-page-root) {
                --chat-right-width: 0px !important;
                --right-panel-width: 0px !important;
            }
            html body .stApp:has(.chat-page-root) .block-container.block-container {
                padding: 0.5rem !important;
            }
            html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
                gap: 0 !important;
                height: calc(100vh - 70px) !important;
                max-height: calc(100vh - 70px) !important;
            }
            html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel) {
                display: none !important;
            }
            .chat-header-inner h2 { font-size: 1.05rem !important; }
            .chat-header-inner p { font-size: 0.76rem !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

st.set_page_config(page_title="Chat | Enterprise RAG", page_icon="R", layout="wide", initial_sidebar_state="expanded")
init_session_state()
init_ui_state()
load_styles()
inject_custom_css()

# Final page-level override for notebook-style chat UX.
st.markdown(
    """
    <style>
    html body .stApp:has(.chat-page-root) {
        --right-panel-width: 64px;
        --chat-right-width: var(--right-panel-width);
        --chat-shell-gap: 0.55rem;
        background: #f5f7fb !important;
    }

    html body .stApp:has(.chat-page-root) [data-testid="stHeader"],
    html body .stApp:has(.chat-page-root) [data-testid="stToolbar"],
    html body .stApp:has(.chat-page-root) [data-testid="stDecoration"],
    html body .stApp:has(.chat-page-root) [data-testid="stStatusWidget"] {
        display: none !important;
        height: 0 !important;
    }

    html body .stApp:has(.chat-page-root) .block-container.block-container {
        max-width: none !important;
        width: 100% !important;
        height: 100vh !important;
        min-height: 100vh !important;
        padding: 0.55rem 0.75rem 0.55rem 0.75rem !important;
        overflow: hidden !important;
        box-sizing: border-box !important;
    }

    html body .stApp:has(.chat-page-root) [data-testid="stVerticalBlock"] {
        gap: 0.38rem !important;
    }

    .chat-header-shell {
        width: 100% !important;
        padding: 0 !important;
        margin: 0 0 0.18rem 0 !important;
    }
    .chat-header-inner {
        width: 100% !important;
        max-width: none !important;
        display: flex !important;
        justify-content: flex-start !important;
        align-items: center !important;
        padding: 0 0.15rem !important;
        margin: 0 !important;
        text-align: left !important;
    }
    .chat-header-inner h2 {
        margin: 0 !important;
        padding: 0 !important;
        font-size: 1.02rem !important;
        line-height: 1.12 !important;
        font-weight: 850 !important;
        letter-spacing: -0.025em !important;
        color: #0f172a !important;
    }
    .chat-header-inner p {
        margin: 0.12rem 0 0 0 !important;
        padding: 0 !important;
        font-size: 0.76rem !important;
        line-height: 1.2 !important;
        color: #64748b !important;
    }

    html body .stApp:has(.chat-page-root) .chat-collection-card {
        margin: 0 !important;
        padding: 0.12rem 0 0.18rem 0 !important;
        width: min(100%, 980px) !important;
    }
    html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stHorizontalBlock"] {
        gap: 0.55rem !important;
        align-items: center !important;
    }
    html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stSelectbox"] {
        margin: 0 !important;
    }
    html body .stApp:has(.chat-page-root) .chat-collection-card [data-baseweb="select"] {
        min-height: 42px !important;
        border-radius: 12px !important;
        background: #111827 !important;
        border: 1px solid #111827 !important;
        cursor: pointer !important;
        box-shadow: 0 8px 20px rgba(15,23,42,0.10) !important;
        overflow: hidden !important;
    }
    html body .stApp:has(.chat-page-root) .chat-collection-card [data-baseweb="select"] * {
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
        font-weight: 750 !important;
    }
    html body .stApp:has(.chat-page-root) .chat-collection-card [data-baseweb="select"] input,
    html body .stApp:has(.chat-page-root) .chat-collection-card [role="combobox"] input,
    html body .stApp:has(.chat-page-root) .chat-collection-card [contenteditable="true"] {
        pointer-events: none !important;
        user-select: none !important;
        caret-color: transparent !important;
        color: transparent !important;
        -webkit-text-fill-color: transparent !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_activate_collection button {
        height: 42px !important;
        min-height: 42px !important;
        border-radius: 12px !important;
        border: 1px solid #d7e2f0 !important;
        background: #ffffff !important;
        color: #0f172a !important;
        font-size: 0.92rem !important;
        font-weight: 850 !important;
        box-shadow: 0 8px 18px rgba(15,23,42,0.05) !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_activate_collection button:hover {
        border-color: #2563eb !important;
        color: #2563eb !important;
        transform: translateY(-1px) !important;
    }
    .chat-active-pill {
        margin: 0 0 0.16rem 0 !important;
        padding: 0 !important;
        line-height: 1 !important;
    }
    .mini-chip {
        display: inline-flex !important;
        align-items: center !important;
        height: 24px !important;
        padding: 0 0.52rem !important;
        border-radius: 8px !important;
        font-size: 0.72rem !important;
        font-weight: 800 !important;
    }
    .mini-chip.ok { color: #047857 !important; background: #ecfdf5 !important; border: 1px solid #bbf7d0 !important; }
    .mini-chip.warn { color: #b45309 !important; background: #fff7ed !important; border: 1px solid #fed7aa !important; }

    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
        display: flex !important;
        align-items: stretch !important;
        gap: var(--chat-shell-gap) !important;
        width: 100% !important;
        height: calc(100vh - 118px) !important;
        min-height: 0 !important;
        overflow: hidden !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel),
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_center_panel) {
        flex: 1 1 auto !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
        height: 100% !important;
        overflow: hidden !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel),
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_right_panel) {
        flex: 0 0 var(--right-panel-width) !important;
        width: var(--right-panel-width) !important;
        min-width: var(--right-panel-width) !important;
        max-width: var(--right-panel-width) !important;
        height: 100% !important;
        overflow: hidden !important;
        transition: flex-basis 0.24s ease, width 0.24s ease, min-width 0.24s ease, max-width 0.24s ease !important;
    }

    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel {
        display: flex !important;
        flex-direction: column !important;
        height: 100% !important;
        min-height: 0 !important;
        width: 100% !important;
        margin: 0 !important;
        padding: 0.65rem 0.8rem !important;
        border: 1px solid #dce8f7 !important;
        border-radius: 18px !important;
        background: #ffffff !important;
        box-shadow: 0 16px 38px rgba(15,23,42,0.055) !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        box-sizing: border-box !important;
        scroll-behavior: smooth !important;
    }
    .chat-empty-state {
        min-height: 110px !important;
        height: auto !important;
        padding: 0.3rem 0 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        color: #94a3b8 !important;
        text-align: center !important;
    }
    .chat-empty-state strong {
        font-size: 0.98rem !important;
        margin-bottom: 0.35rem !important;
        color: #64748b !important;
    }
    .chat-empty-state span {
        font-size: 0.88rem !important;
    }
    .message-row {
        margin: 0 0 0.45rem 0 !important;
    }
    .streaming-row {
        width: 100% !important;
        justify-content: flex-start !important;
    }
    .chat-bubble-ai, .chat-bubble-user {
        max-width: 82% !important;
        border-radius: 16px !important;
        padding: 0.62rem 0.78rem !important;
        line-height: 1.52 !important;
        font-size: 0.88rem !important;
        overflow-wrap: anywhere !important;
    }
    .chat-bubble-ai {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        color: #0f172a !important;
        box-shadow: 0 8px 20px rgba(15,23,42,0.045) !important;
    }
    .chat-bubble-user {
        background: #111827 !important;
        color: #ffffff !important;
    }
    .streaming-cursor {
        display: inline-block !important;
        width: 6px !important;
        height: 1em !important;
        margin-left: 3px !important;
        vertical-align: -2px !important;
        background: #2563eb !important;
        animation: chatBlink 0.9s steps(2, start) infinite !important;
    }
    @keyframes chatBlink { 50% { opacity: 0; } }
    .stream-status {
        display: inline-flex !important;
        align-items: center !important;
        gap: 0.35rem !important;
        margin: 0.15rem 0 0.4rem 0 !important;
        padding: 0.32rem 0.55rem !important;
        border-radius: 999px !important;
        background: #eff6ff !important;
        color: #1d4ed8 !important;
        border: 1px solid #bfdbfe !important;
        font-size: 0.76rem !important;
        font-weight: 750 !important;
    }

    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
        position: sticky !important;
        bottom: 0 !important;
        z-index: 50 !important;
        width: min(100%, 980px) !important;
        margin: auto auto 0 auto !important;
        padding: 0.38rem !important;
        border: 1px solid #cbd8e8 !important;
        border-radius: 24px !important;
        background: rgba(255,255,255,0.98) !important;
        box-shadow: 0 18px 36px rgba(15,23,42,0.11) !important;
        backdrop-filter: blur(10px) !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        align-items: center !important;
        gap: 0.42rem !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input {
        height: 42px !important;
        min-height: 42px !important;
        border: 0 !important;
        border-radius: 18px !important;
        background: #ffffff !important;
        color: #0f172a !important;
        -webkit-text-fill-color: #0f172a !important;
        font-size: 0.92rem !important;
        box-shadow: none !important;
        outline: none !important;
        padding: 0 0.75rem !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input::placeholder {
        color: #64748b !important;
        -webkit-text-fill-color: #64748b !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button {
        width: 42px !important;
        min-width: 42px !important;
        height: 42px !important;
        min-height: 42px !important;
        border-radius: 999px !important;
        padding: 0 !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        background: #111827 !important;
        color: #ffffff !important;
        border: 0 !important;
        font-size: 1.05rem !important;
        font-weight: 900 !important;
        box-shadow: 0 12px 24px rgba(15,23,42,0.22) !important;
        transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.16s ease !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button:hover {
        transform: translateY(-1px) scale(1.03) !important;
        background: #2563eb !important;
        box-shadow: 0 14px 28px rgba(37,99,235,0.28) !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stToggle"],
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stCheckbox"] {
        width: 42px !important;
        height: 42px !important;
        border-radius: 999px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        background: #f1f5f9 !important;
        border: 1px solid #dbe7f5 !important;
        transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stToggle"]:hover,
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stCheckbox"]:hover {
        transform: translateY(-1px) !important;
        border-color: #2563eb !important;
        background: #eff6ff !important;
    }

    html body .stApp:has(.chat-page-root) .st-key-chat_right_panel {
        height: 100% !important;
        width: 100% !important;
        min-width: 0 !important;
        padding: 0.48rem !important;
        border: 1px solid #dce8f7 !important;
        border-radius: 18px !important;
        background: #ffffff !important;
        box-shadow: 0 16px 38px rgba(15,23,42,0.07) !important;
        overflow-x: hidden !important;
        overflow-y: auto !important;
        box-sizing: border-box !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_right_panel .stButton > button {
        width: 100% !important;
        min-height: 38px !important;
        border-radius: 14px !important;
        background: #111827 !important;
        color: #ffffff !important;
        border: 1px solid #111827 !important;
        font-weight: 850 !important;
        box-shadow: none !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_right_panel .stButton > button:hover {
        background: #2563eb !important;
        border-color: #2563eb !important;
        transform: translateY(-1px) !important;
    }
    .chat-right-icon-rail {
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        gap: 0.55rem !important;
        padding-top: 0.45rem !important;
        width: 100% !important;
    }
    .chat-right-icon {
        width: 40px !important;
        height: 40px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        border-radius: 14px !important;
        border: 1px solid #dbe7f5 !important;
        background: linear-gradient(180deg,#ffffff 0%,#f7fbff 100%) !important;
        box-shadow: 0 8px 18px rgba(15,23,42,0.055) !important;
        font-size: 1.04rem !important;
        opacity: 1 !important;
        transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease !important;
    }
    .chat-right-icon:hover {
        transform: translateY(-1px) !important;
        border-color: #2563eb !important;
        background: #eff6ff !important;
    }
    .chat-right-panel-head {
        padding: 0.12rem 0.08rem 0.55rem !important;
    }
    .chat-right-panel-head strong {
        display: block !important;
        font-size: 0.98rem !important;
        line-height: 1.12 !important;
        color: #0f172a !important;
        font-weight: 850 !important;
    }
    .chat-right-panel-head span {
        display: block !important;
        margin-top: 0.1rem !important;
        font-size: 0.74rem !important;
        color: #64748b !important;
    }
    .chat-tool-grid {
        display: grid !important;
        grid-template-columns: repeat(2, minmax(0,1fr)) !important;
        gap: 0.55rem !important;
        margin-top: 0.55rem !important;
    }
    .chat-tool-card {
        min-height: 72px !important;
        padding: 0.58rem !important;
        border-radius: 14px !important;
        border: 1px solid #dbe7f5 !important;
        background: #f8fbff !important;
        box-shadow: none !important;
        align-items: flex-start !important;
        text-align: left !important;
    }
    .chat-tool-card span { font-size: 1.25rem !important; margin-bottom: 0.25rem !important; }
    .chat-tool-card strong { font-size: 0.68rem !important; line-height: 1.1 !important; color: #0f172a !important; }
    .chat-tool-card em { font-size: 0.61rem !important; color: #94a3b8 !important; }
    .chat-tool-card strong, .chat-tool-card em {
        max-width: 100% !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }

    html body .stApp:has(.chat-page-root) .copy-action-label,
    html body .stApp:has(.chat-page-root) .stCodeBlock {
        display: none !important;
    }

    @media (max-width: 920px) {
        html body .stApp:has(.chat-page-root) { --right-panel-width: 0px !important; }
        html body .stApp:has(.chat-page-root) .block-container.block-container { padding: 0.5rem !important; }
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
            height: calc(100vh - 94px) !important;
            gap: 0 !important;
        }
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel),
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_right_panel) {
            display: none !important;
        }
        html body .stApp:has(.chat-page-root) .chat-collection-card [data-testid="stHorizontalBlock"] {
            gap: 0.4rem !important;
        }
        .chat-header-inner h2 { font-size: 0.96rem !important; }
        .chat-header-inner p { font-size: 0.72rem !important; }
    }


    /* ===== GOOGLE NOTEBOOKLM STYLE FINAL OVERRIDE ===== */
    html body .stApp:has(.chat-page-root) {
        --right-panel-width: var(--right-panel-width, 72px) !important;
        --chat-bg: #f7f9fc !important;
        --card-border: #dbe6f3 !important;
        --text-main: #0f172a !important;
        --text-soft: #64748b !important;
        background: var(--chat-bg) !important;
    }

    html body .stApp:has(.chat-page-root) .block-container.block-container {
        padding: 0.85rem 1.45rem 0.65rem 1.45rem !important;
        height: 100vh !important;
        min-height: 100vh !important;
        max-height: 100vh !important;
        overflow: hidden !important;
        background: var(--chat-bg) !important;
        box-sizing: border-box !important;
    }

    .chat-header-shell { margin: 0 0 0.45rem 0 !important; padding: 0 !important; }
    .chat-header-inner { max-width: none !important; padding: 0 !important; margin: 0 !important; }
    .chat-header-inner h2 {
        font-size: 1.02rem !important;
        line-height: 1.15 !important;
        color: #07111f !important;
        font-weight: 850 !important;
        letter-spacing: -0.025em !important;
    }
    .chat-header-inner p {
        margin-top: 0.12rem !important;
        font-size: 0.76rem !important;
        color: #53657e !important;
    }

    html body .stApp:has(.chat-page-root) [data-testid="stVerticalBlock"] { gap: 0.42rem !important; }

    /* Top selector row */
    .chat-collection-card {
        margin: 0 !important;
        padding: 0 0 0.28rem 0 !important;
    }
    .chat-collection-card [data-testid="stHorizontalBlock"] {
        gap: 0.75rem !important;
        align-items: center !important;
    }
    .chat-collection-card [data-baseweb="select"] {
        min-height: 46px !important;
        height: 46px !important;
        border-radius: 16px !important;
        border: 1px solid #d8e3f1 !important;
        background: #ffffff !important;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.055) !important;
        outline: none !important;
        cursor: pointer !important;
        overflow: hidden !important;
    }
    .chat-collection-card [data-baseweb="select"] *,
    .chat-collection-card [role="combobox"] * {
        background-color: transparent !important;
        color: #0f172a !important;
        -webkit-text-fill-color: #0f172a !important;
        font-weight: 760 !important;
        font-size: 0.92rem !important;
        text-shadow: none !important;
    }
    .chat-collection-card [data-baseweb="select"]:hover,
    .chat-collection-card [data-baseweb="select"]:focus-within {
        border-color: #b8c9de !important;
        box-shadow: 0 10px 22px rgba(15, 23, 42, 0.075) !important;
        background: #ffffff !important;
    }
    .chat-collection-card [data-baseweb="select"] input,
    .chat-collection-card [role="combobox"] input,
    .chat-collection-card [contenteditable="true"] {
        opacity: 0 !important;
        width: 0 !important;
        max-width: 0 !important;
        caret-color: transparent !important;
        pointer-events: none !important;
        user-select: none !important;
    }
    .st-key-chat_activate_collection button {
        height: 46px !important;
        min-height: 46px !important;
        border-radius: 16px !important;
        border: 1px solid #d8e3f1 !important;
        background: #ffffff !important;
        color: #0f172a !important;
        font-weight: 850 !important;
        font-size: 0.95rem !important;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.045) !important;
    }
    .st-key-chat_activate_collection button:hover {
        background: #f8fbff !important;
        border-color: #b8c9de !important;
        color: #0f172a !important;
        transform: translateY(-1px) !important;
    }
    .chat-active-pill { margin: 0 !important; padding: 0.05rem 0 0.25rem 0 !important; }
    .mini-chip {
        min-height: 24px !important;
        padding: 0.15rem 0.55rem !important;
        border-radius: 999px !important;
        font-size: 0.72rem !important;
        font-weight: 820 !important;
    }

    /* Main row: one-page Notebook layout */
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
        height: calc(100vh - 148px) !important;
        min-height: 430px !important;
        max-height: calc(100vh - 148px) !important;
        gap: 0.9rem !important;
        overflow: hidden !important;
        align-items: stretch !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel),
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_center_panel) {
        flex: 1 1 auto !important;
        width: auto !important;
        min-width: 0 !important;
        max-width: none !important;
        height: 100% !important;
        overflow: hidden !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel),
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_right_panel) {
        flex: 0 0 var(--right-panel-width) !important;
        width: var(--right-panel-width) !important;
        min-width: var(--right-panel-width) !important;
        max-width: var(--right-panel-width) !important;
        height: 100% !important;
        overflow: hidden !important;
        padding: 0 !important;
        transition: flex-basis 0.22s ease, width 0.22s ease, min-width 0.22s ease, max-width 0.22s ease !important;
    }

    /* Center chat card */
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel {
        height: 100% !important;
        min-height: 0 !important;
        width: 100% !important;
        max-width: none !important;
        margin: 0 !important;
        padding: 0.75rem 0.85rem 0.72rem 0.85rem !important;
        border: 1px solid var(--card-border) !important;
        border-radius: 18px !important;
        background: #ffffff !important;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.035) !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        display: flex !important;
        flex-direction: column !important;
        box-sizing: border-box !important;
    }
    .chat-empty-state {
        min-height: 0 !important;
        flex: 1 1 auto !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        padding: 1rem 0 0.5rem 0 !important;
        color: #8794a8 !important;
    }
    .chat-empty-state strong {
        font-size: 0.98rem !important;
        color: #526173 !important;
        margin-bottom: 0.36rem !important;
    }
    .chat-empty-state span { font-size: 0.9rem !important; color: #8a96aa !important; }

    /* Composer: clean bottom input */
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
        position: sticky !important;
        bottom: 0 !important;
        z-index: 50 !important;
        width: 100% !important;
        margin: 0.55rem 0 0 0 !important;
        padding: 0.34rem 0.42rem !important;
        border: 1px solid #cfdced !important;
        border-radius: 24px !important;
        background: rgba(255,255,255,0.98) !important;
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.10) !important;
        box-sizing: border-box !important;
        flex-shrink: 0 !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        gap: 0.4rem !important;
        align-items: center !important;
        margin: 0 !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stColumn"]:first-child,
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="column"]:first-child,
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="stColumn"]:last-child,
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] [data-testid="column"]:last-child {
        flex: 0 0 48px !important;
        width: 48px !important;
        min-width: 48px !important;
        max-width: 48px !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input {
        height: 44px !important;
        min-height: 44px !important;
        border: 0 !important;
        border-radius: 16px !important;
        background: transparent !important;
        color: #0f172a !important;
        -webkit-text-fill-color: #0f172a !important;
        font-size: 0.92rem !important;
        font-weight: 460 !important;
        box-shadow: none !important;
        outline: none !important;
        padding: 0 0.4rem !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stTextInput"] input::placeholder {
        color: #667792 !important;
        -webkit-text-fill-color: #667792 !important;
        opacity: 1 !important;
    }

    /* Web-search toggle pill */
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stToggle"],
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stCheckbox"] {
        width: 44px !important;
        height: 38px !important;
        min-height: 38px !important;
        border-radius: 999px !important;
        background: #eef4fb !important;
        border: 1px solid #d8e3f1 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 0 !important;
        margin: 0 !important;
        overflow: hidden !important;
        transition: all 0.18s ease !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stToggle"]:hover,
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stCheckbox"]:hover {
        background: #e3ecf8 !important;
        border-color: #b8c9de !important;
        transform: translateY(-1px) !important;
    }

    /* Send button */
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button {
        width: 44px !important;
        height: 44px !important;
        min-width: 44px !important;
        max-width: 44px !important;
        border-radius: 999px !important;
        border: 0 !important;
        background: #101827 !important;
        color: #ffffff !important;
        font-size: 1.08rem !important;
        line-height: 1 !important;
        font-weight: 900 !important;
        padding: 0 !important;
        box-shadow: 0 9px 18px rgba(15, 23, 42, 0.24) !important;
        overflow: hidden !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stFormSubmitButton"] button:hover {
        background: #2563eb !important;
        transform: translateY(-1px) !important;
        color: #ffffff !important;
    }

    /* Right Studio rail */
    html body .stApp:has(.chat-page-root) .st-key-chat_right_panel {
        height: 100% !important;
        min-height: 0 !important;
        width: 100% !important;
        padding: 0.52rem !important;
        border: 1px solid #dbe6f3 !important;
        border-radius: 22px !important;
        background: #ffffff !important;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.055) !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        box-sizing: border-box !important;
    }
    .st-key-chat_right_panel .stButton button,
    .st-key-chat_right_panel button {
        width: 44px !important;
        height: 44px !important;
        min-width: 44px !important;
        border-radius: 15px !important;
        background: #111827 !important;
        color: #ffffff !important;
        border: 1px solid #111827 !important;
        font-size: 1rem !important;
        padding: 0 !important;
        box-shadow: none !important;
        margin: 0 auto 0.55rem auto !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    .st-key-chat_right_panel .stButton button:hover,
    .st-key-chat_right_panel button:hover {
        background: #2563eb !important;
        border-color: #2563eb !important;
        color: #ffffff !important;
    }
    .chat-right-icon-rail {
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: flex-start !important;
        gap: 0.42rem !important;
        width: 100% !important;
        padding: 0.2rem 0 0.3rem 0 !important;
    }
    .chat-right-icon {
        width: 44px !important;
        height: 44px !important;
        border-radius: 15px !important;
        border: 1px solid #dce7f4 !important;
        background: #f8fbff !important;
        color: #1e293b !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 1.05rem !important;
        font-weight: 800 !important;
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.045) !important;
        line-height: 1 !important;
        opacity: 1 !important;
        overflow: hidden !important;
    }
    .chat-right-icon:hover {
        background: #eef5ff !important;
        border-color: #bcd0ea !important;
        transform: translateY(-1px) !important;
    }
    .chat-right-panel-head strong { font-size: 0.95rem !important; color: #0f172a !important; }
    .chat-right-panel-head span { font-size: 0.72rem !important; color: #64748b !important; }
    .chat-tool-grid { gap: 0.55rem !important; grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
    .chat-tool-card {
        min-height: 72px !important;
        border-radius: 16px !important;
        border: 1px solid #e0e9f5 !important;
        background: #f8fbff !important;
        padding: 0.55rem !important;
    }

    /* Streaming answer visible in same chat card */
    .stream-status {
        display: inline-flex !important;
        align-items: center !important;
        gap: 0.4rem !important;
        margin: 0.35rem 0 !important;
        padding: 0.35rem 0.65rem !important;
        border-radius: 999px !important;
        background: #eef5ff !important;
        color: #315f9e !important;
        font-size: 0.76rem !important;
        font-weight: 760 !important;
    }
    .chat-bubble-ai, .chat-bubble-user {
        font-size: 0.88rem !important;
        line-height: 1.55 !important;
    }

    @media (max-width: 1050px) {
        html body .stApp:has(.chat-page-root) { --right-panel-width: 72px !important; }
        .chat-tool-grid, .chat-right-panel-head, .chat-right-sources-action, .refs-drawer { display: none !important; }
    }
    @media (max-width: 760px) {
        html body .stApp:has(.chat-page-root) .block-container.block-container { padding: 0.6rem !important; }
        html body .stApp:has(.chat-page-root) { --right-panel-width: 0px !important; }
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) { height: calc(100vh - 128px) !important; gap: 0 !important; }
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel),
        html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_right_panel) { display: none !important; }
    }

    .st-key-chat_top_toolbar {
        margin: 0 0 0.18rem !important;
        padding: 0 !important;
    }
    .st-key-chat_top_toolbar > div,
    .st-key-chat_top_toolbar [data-testid="stVerticalBlock"] {
        gap: 0 !important;
    }
    .st-key-chat_top_toolbar > div > [data-testid="stHorizontalBlock"]:has(.chat-header-shell):has(.st-key-chat_collection_selector) {
        align-items: center !important;
        display: grid !important;
        gap: 0.5rem !important;
        grid-template-columns: minmax(190px, 0.26fr) minmax(300px, 0.54fr) minmax(130px, 0.2fr) !important;
        margin: 0 !important;
        max-width: none !important;
        width: 100% !important;
    }
    .st-key-chat_top_toolbar [data-testid="stColumn"] {
        align-self: center !important;
        flex: none !important;
        max-width: none !important;
        min-width: 0 !important;
        width: auto !important;
    }
    .st-key-chat_top_toolbar .chat-header-shell,
    .st-key-chat_top_toolbar .chat-collection-card,
    .st-key-chat_top_toolbar .chat-active-pill {
        margin: 0 !important;
        padding: 0 !important;
    }
    .st-key-chat_top_toolbar .chat-header-shell h2,
    .st-key-chat_top_toolbar .chat-active-pill {
        white-space: nowrap !important;
    }
    .st-key-chat_top_toolbar .chat-active-pill {
        box-sizing: border-box !important;
        max-width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
        width: 100% !important;
    }
    .st-key-chat_top_toolbar .chat-active-pill .mini-chip {
        box-sizing: border-box !important;
        display: block !important;
        max-width: 100% !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
    }
    .st-key-chat_top_toolbar > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] [data-testid="stHorizontalBlock"]:has(.st-key-chat_collection_selector) {
        gap: 0.45rem !important;
        grid-template-columns: minmax(0, 1fr) 96px !important;
        max-width: none !important;
        width: 100% !important;
    }
    .st-key-chat_top_toolbar .st-key-chat_activate_collection,
    .st-key-chat_top_toolbar .st-key-chat_activate_collection button {
        width: 96px !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_right_panel),
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_right_panel) {
        top: 76px !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) .st-key-chat_center_panel {
        height: calc(100vh - 126px) !important;
        max-height: calc(100vh - 126px) !important;
    }
    .st-key-chat_center_panel,
    .st-key-chat_center_panel * {
        overflow-anchor: none;
    }
    .st-key-chat_center_panel .chat-scroll-anchor {
        display: block !important;
        height: 1px !important;
        overflow-anchor: auto !important;
        width: 100% !important;
    }
    html body .stApp:has(.chat-page-root) .block-container.block-container {
        padding-top: 0.08rem !important;
    }
    .st-key-chat_top_toolbar {
        box-sizing: border-box !important;
        margin-top: -0.35rem !important;
        padding-right: 60px !important;
        width: 100% !important;
    }
    .st-key-chat_top_toolbar > div > [data-testid="stHorizontalBlock"]:has(.chat-header-shell):has(.st-key-chat_collection_selector) {
        grid-template-columns: minmax(190px, 0.26fr) minmax(300px, 1fr) minmax(110px, 220px) !important;
    }
    .st-key-chat_top_toolbar .chat-active-pill {
        justify-self: start !important;
        max-width: 220px !important;
        width: auto !important;
    }
    .st-key-chat_top_toolbar .chat-active-pill .mini-chip {
        width: auto !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) .st-key-chat_center_panel {
        height: calc(100vh - 118px) !important;
        max-height: calc(100vh - 118px) !important;
    }
    @media (max-width: 900px) {
        .st-key-chat_top_toolbar {
            margin-top: 0 !important;
            padding-right: 0 !important;
        }
        .st-key-chat_top_toolbar > div > [data-testid="stHorizontalBlock"]:has(.chat-header-shell):has(.st-key-chat_collection_selector) {
            grid-template-columns: minmax(150px, 0.25fr) minmax(240px, 1fr) minmax(100px, 180px) !important;
        }
        .st-key-chat_top_toolbar .chat-active-pill {
            max-width: 180px !important;
        }
    }
    @media (max-width: 700px) {
        .st-key-chat_top_toolbar > div > [data-testid="stHorizontalBlock"]:has(.chat-header-shell):has(.st-key-chat_collection_selector) {
            grid-template-columns: minmax(0, 1fr) !important;
        }
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) .st-key-chat_center_panel {
        padding-bottom: 84px !important;
        scroll-padding-bottom: 84px !important;
    }
    .chat-bottom-safe-space {
        flex: 1 1 auto !important;
        height: auto !important;
        min-height: 44px !important;
    }
    .chat-scroll-anchor {
        display: block !important;
        height: 1px !important;
        margin-bottom: 0 !important;
        overflow-anchor: auto !important;
        width: 100% !important;
    }
    .message-row.assistant {
        align-items: center !important;
    }
    .chat-bubble-ai {
        max-width: min(920px, calc(100% - 1.5rem)) !important;
        width: auto !important;
    }
    .message-row.user {
        align-items: flex-end !important;
    }
    .chat-bubble-user {
        max-width: min(560px, calc(100% - 1.5rem)) !important;
        width: auto !important;
    }
    html body .stApp:has(.chat-page-root) .block-container.block-container {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    .st-key-chat_top_toolbar {
        margin-top: -0.65rem !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
        height: calc(100vh - 104px) !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) .st-key-chat_center_panel {
        height: calc(100vh - 104px) !important;
        max-height: calc(100vh - 104px) !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stAppViewBlockContainer"],
    html body .stApp:has(.chat-page-root) .block-container.block-container,
    html body .stApp:has(.chat-page-root) main .block-container {
        margin-top: 0 !important;
        padding-top: 0.55rem !important;
    }
    .st-key-chat_top_toolbar {
        margin-bottom: 0.35rem !important;
        margin-top: 0 !important;
        overflow: visible !important;
        padding-right: 72px !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) {
        height: calc(100vh - 132px) !important;
        max-height: calc(100vh - 132px) !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) .st-key-chat_center_panel {
        height: calc(100vh - 132px) !important;
        max-height: calc(100vh - 132px) !important;
        overflow-y: auto !important;
        padding: 0.55rem 0.75rem 76px !important;
        scroll-padding-bottom: 96px !important;
    }
    .st-key-chat_live_response_slot {
        background: transparent !important;
        bottom: 88px !important;
        margin: 0 !important;
        max-width: 100% !important;
        padding: 0 !important;
        position: sticky !important;
        width: 100% !important;
        z-index: 18 !important;
    }
    .st-key-chat_live_response_slot .message-row {
        margin-left: auto !important;
        margin-right: auto !important;
        max-width: min(920px, calc(100% - 1.25rem)) !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
        bottom: 10px !important;
        margin: auto auto 0 !important;
        max-width: none !important;
        position: sticky !important;
        width: calc(100% - 1.2rem) !important;
        z-index: 20 !important;
    }
    .st-key-chat_center_panel {
        display: flex !important;
        flex-direction: column !important;
        padding-bottom: 0.75rem !important;
    }
    html body .stApp:has(.chat-page-root) .st-key-chat_center_panel [data-testid="stForm"] {
        bottom: 0.65rem !important;
        box-sizing: border-box !important;
        left: auto !important;
        margin: auto auto 0 !important;
        max-height: none !important;
        max-width: min(920px, calc(100% - 1.25rem)) !important;
        min-height: 0 !important;
        position: sticky !important;
        right: auto !important;
        top: auto !important;
        transform: none !important;
        width: min(920px, calc(100% - 1.25rem)) !important;
        z-index: 30 !important;
    }
    .chat-bottom-safe-space {
        flex: 1 1 auto !important;
        min-height: 44px !important;
    }
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="stColumn"]:has(.st-key-chat_center_panel),
    html body .stApp:has(.chat-page-root) [data-testid="stHorizontalBlock"]:has(.st-key-chat_right_panel) > [data-testid="column"]:has(.st-key-chat_center_panel) {
        min-width: 0 !important;
        width: auto !important;
    }
    .chat-bottom-safe-space {
        flex: 1 1 auto !important;
        height: auto !important;
        min-height: 44px !important;
    }
    .chat-scroll-focus {
        appearance: none !important;
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        display: block !important;
        height: 1px !important;
        margin: 0 !important;
        opacity: 0 !important;
        outline: none !important;
        padding: 0 !important;
        pointer-events: none !important;
        width: 1px !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


if not require_login("Chat"):
    st.stop()

require_runtime_credentials("chat")
render_runtime_sidebar()

st.markdown('<div class="chat-page-root" aria-hidden="true"></div>', unsafe_allow_html=True)
workspace_col, source_panel = render_chat_layout()

with workspace_col:
    active_collection = _active_display_collection()
    active_physical_collection = _active_physical_collection()
    chip_class = "ok" if active_physical_collection and st.session_state.get("session_id") else "warn"
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

    messages_slot = st.container(key="chat_center_panel")

existing_messages = st.session_state.get("chat_history") or st.session_state.get("messages") or []
if existing_messages:
    st.markdown('<span class="chat-has-messages" aria-hidden="true"></span>', unsafe_allow_html=True)

with messages_slot:
    if existing_messages:
        _render_messages(existing_messages)
        _render_chat_autoscroll()
    else:
        st.markdown(
            """
            <div class="chat-empty-state">
              <strong>Ready for your documents</strong>
              <span>Activate a collection, then ask a question.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    live_response_slot = st.container(key="chat_live_response_slot")
    _render_chat_bottom_spacer()
    question, manual_web_search_allowed = _render_chat_composer(active_collection if st.session_state.get("session_id") else None)

approved_web_search = None
question = approved_web_search.get("question") if approved_web_search else question
allow_web_search = bool(approved_web_search) or manual_web_search_allowed

if question:
    active_collection = _active_display_collection()
    active_physical_collection = _active_physical_collection()
    if not active_physical_collection or not st.session_state.session_id:
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
    answer_length = get_answer_length_instruction()
    meta = {
        "streaming": True,
        "response_mode": "streaming",
        "trace_steps": [],
        "allow_web_search": allow_web_search,
    }

    with live_response_slot:
        placeholder = st.empty()
        progress = st.empty()
        try:
            progress.markdown('<div class="stream-status">Searching selected collection...</div>', unsafe_allow_html=True)
            for event, payload in chat_stream(
                st.session_state.session_id,
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
                        _bubble_html("".join(answer_parts), "assistant", streaming=True)
                        + '<span class="chat-scroll-anchor"></span>',
                        unsafe_allow_html=True,
                    )
                    _render_chat_autoscroll()
                    time.sleep(0.008)
                elif event == "done":
                    final_answer = payload.get("answer") or "".join(answer_parts)
                    sources = _answer_references(_payload_sources(payload, sources))
                    meta = normalize_agentic_metadata(payload, meta)
                elif event == "trace":
                    meta = normalize_agentic_metadata(
                        {"trace_steps": [*meta.get("trace_steps", []), payload]},
                        meta,
                    )
                elif event == "error":
                    raise ApiClientError(payload.get("message") or "Streaming chat failed.")

            progress.empty()
            final_answer = final_answer.strip()
            if final_answer:
                placeholder.empty()
                render_message_card("assistant", final_answer, key=f"chat_live_assistant_{len(st.session_state.chat_history)}", meta=meta)
                assistant_message = {"role": "assistant", "content": final_answer, "sources": sources, "meta": meta}
                st.session_state.chat_history.append(assistant_message)
                st.session_state.messages = st.session_state.chat_history
                st.session_state.last_meta = meta
                _save_query_log(question, final_answer, sources, meta)
                _render_chat_bottom_spacer()
                _render_chat_autoscroll()
            
            st.rerun()
        except ApiClientError as exc:
            progress.empty()
            placeholder.empty()
            st.error(f"Chat failed: {str(exc)}")
            st.rerun()
        finally:
            st.session_state.chat_generating = False
