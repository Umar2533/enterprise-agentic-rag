import asyncio
import base64
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

import requests
import streamlit as st
import streamlit.components.v1 as components

from components.runtime_secrets import (
    clear_runtime_key_state,
    default_embedding_provider,
    get_secret_value,
    runtime_secret_payload,
)


API_BASE_URL = os.getenv("RAG_API_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 350
COLLECTION_ACTIVATION_TIMEOUT = 60
AUTH_STORAGE_COMPONENT_PATH = Path(__file__).resolve().parents[1] / "components" / "auth_storage_component"
_browser_auth_storage_component = components.declare_component(
    "browser_auth_storage",
    path=str(AUTH_STORAGE_COMPONENT_PATH),
)
logger = logging.getLogger(__name__)
USER_SCOPED_SESSION_KEYS = (
    "chat_history",
    "messages",
    "query_logs",
    "active_query_log_id",
    "last_sources",
    "last_meta",
    "last_answer",
    "last_trace",
    "chat_export_pdf",
    "latest_pdf_bytes",
    "latest_pdf_signature",
    "active_collection",
    "active_collection_name",
    "active_collection_display_name",
    "collection_name",
    "selected_collection",
    "attached_collection",
    "session_id",
    "active_session_id",
    "chat_dropdown_collection",
    "chat_scroll_after_rerun",
    "chat_scroll_marker",
    "recent_scroll_seen_log_id",
    "collection_build_summary",
    "filename",
    "app_graph",
    "agent_ready",
    "attach_status",
    "last_attach_error",
    "retrieval_mode",
    "retrieval_warning",
    "refs_panel_open",
)
try:
    import httpx
except ImportError:  # pragma: no cover - httpx is optional for this client.
    httpx = None


class ApiClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        *,
        exception_type: str = "",
        elapsed_seconds: float | None = None,
        timeout_value: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.exception_type = exception_type
        self.elapsed_seconds = elapsed_seconds
        self.timeout_value = timeout_value


class ApiClientDisconnect(ApiClientError):
    """Raised when a streaming response is closed by the client or network."""


def _winerror(exc: BaseException) -> int | None:
    current = exc
    seen = set()
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        winerror = getattr(current, "winerror", None)
        if winerror is not None:
            return int(winerror)
        current = current.__cause__ or current.__context__
    return None


def _is_transient_connection_exception(exc: BaseException) -> bool:
    httpx_timeout = (httpx.TimeoutException,) if httpx is not None else ()
    httpx_connection = (httpx.ConnectError, httpx.ReadError) if httpx is not None else ()
    if isinstance(exc, (requests.Timeout, requests.ConnectionError, ConnectionResetError, *httpx_timeout, *httpx_connection)):
        return True
    return isinstance(exc, OSError) and _winerror(exc) == 10054


def _activation_exception_message(exc: BaseException) -> str:
    if isinstance(exc, requests.Timeout) or (httpx is not None and isinstance(exc, httpx.TimeoutException)):
        return f"{type(exc).__name__}: {exc}"
    if isinstance(exc, (requests.ConnectionError, ConnectionResetError)) or (
        httpx is not None and isinstance(exc, (httpx.ConnectError, httpx.ReadError))
    ):
        return f"{type(exc).__name__}: {exc}"
    if isinstance(exc, OSError) and _winerror(exc) == 10054:
        return f"{type(exc).__name__}: {exc}"
    return f"{type(exc).__name__}: {exc}"


def _request(method: str, path: str, **kwargs) -> Dict[str, Any]:
    return _request_once(method, path, allow_auth_refresh=True, **kwargs)


def _request_once(
    method: str,
    path: str,
    allow_auth_refresh: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    timeout = kwargs.pop("timeout", (CONNECT_TIMEOUT, READ_TIMEOUT))
    max_attempts = max(1, int(kwargs.pop("max_attempts", 3)))
    headers = kwargs.pop("headers", None)
    url = f"{API_BASE_URL}{path}"
    response = None
    last_error = None
    request_started_at = time.time()
    request_start = time.monotonic()
    if path == "/collections/select":
        logger.info(
            "collection_select_request_start request_start_time=%.3f timeout_value=%s max_attempts=%s",
            request_started_at,
            timeout,
            max_attempts,
        )
    for attempt in range(max_attempts):
        transient_failure = False
        try:
            response = requests.request(
                method,
                url,
                headers=_backend_headers(headers, path=path),
                timeout=timeout,
                **kwargs,
            )
            break
        except requests.Timeout as exc:
            elapsed = time.monotonic() - request_start
            last_error = ApiClientError(
                _activation_exception_message(exc) if path == "/collections/select" else "Backend request timed out. Please try again.",
                exception_type=type(exc).__name__,
                elapsed_seconds=elapsed,
                timeout_value=timeout,
            )
            transient_failure = True
            if path == "/collections/select":
                logger.warning(
                    "collection_select_request_exception elapsed_seconds=%.3f timeout_value=%s exception_type=%s response_status_code=%s retry_attempt=%s",
                    elapsed,
                    timeout,
                    type(exc).__name__,
                    None,
                    attempt + 1,
                )
        except requests.ConnectionError as exc:
            elapsed = time.monotonic() - request_start
            last_error = ApiClientError(
                _activation_exception_message(exc) if path == "/collections/select" else "Backend is not reachable. Start FastAPI on port 8000.",
                exception_type=type(exc).__name__,
                elapsed_seconds=elapsed,
                timeout_value=timeout,
            )
            transient_failure = True
            if path == "/collections/select":
                logger.warning(
                    "collection_select_request_exception elapsed_seconds=%.3f timeout_value=%s exception_type=%s response_status_code=%s retry_attempt=%s",
                    elapsed,
                    timeout,
                    type(exc).__name__,
                    None,
                    attempt + 1,
                )
        except OSError as exc:
            elapsed = time.monotonic() - request_start
            last_error = ApiClientError(
                _activation_exception_message(exc),
                exception_type=type(exc).__name__,
                elapsed_seconds=elapsed,
                timeout_value=timeout,
            )
            transient_failure = _is_transient_connection_exception(exc)
            if path == "/collections/select":
                logger.warning(
                    "collection_select_request_exception elapsed_seconds=%.3f timeout_value=%s exception_type=%s winerror=%s response_status_code=%s retry_attempt=%s",
                    elapsed,
                    timeout,
                    type(exc).__name__,
                    _winerror(exc),
                    None,
                    attempt + 1,
                )
        except requests.RequestException as exc:
            elapsed = time.monotonic() - request_start
            last_error = ApiClientError(
                f"Backend request failed: {exc}",
                exception_type=type(exc).__name__,
                elapsed_seconds=elapsed,
                timeout_value=timeout,
            )
            if path == "/collections/select":
                logger.warning(
                    "collection_select_request_exception elapsed_seconds=%.3f timeout_value=%s exception_type=%s response_status_code=%s retry_attempt=%s",
                    elapsed,
                    timeout,
                    type(exc).__name__,
                    None,
                    attempt + 1,
                )
        if path == "/collections/select" and not transient_failure:
            break
        if attempt < max_attempts - 1:
            time.sleep(0.75 if path == "/collections/select" else 0.4 * (attempt + 1))
    if response is None:
        raise last_error or ApiClientError("Backend request failed.")
    if path == "/collections/select":
        logger.info(
            "collection_select_response elapsed_seconds=%.3f timeout_value=%s response_status_code=%s",
            time.monotonic() - request_start,
            timeout,
            response.status_code,
        )

    if path in {"/auth/login", "/auth/refresh", "/auth/logout"}:
        logger.debug("Auth %s Set-Cookie header present: %s", path, "set-cookie" in response.headers)

    if response.ok:
        return response.json()

    if _should_refresh_auth(response, path, allow_auth_refresh) and refresh_access_token(
        show_expired_message=False,
        clear_on_failure=False,
    ):
        return _request_once(
            method,
            path,
            allow_auth_refresh=False,
            headers=headers,
            timeout=timeout,
            max_attempts=max_attempts,
            **kwargs,
        )

    try:
        error_payload = response.json()
        detail = (
            error_payload.get("detail")
            or error_payload.get("error")
            or error_payload.get("message")
            or response.text
        )
    except ValueError:
        detail = response.text
    raise ApiClientError(
        str(detail),
        status_code=response.status_code,
        exception_type="HTTPStatusError",
        elapsed_seconds=time.monotonic() - request_start,
        timeout_value=timeout,
    )


def health() -> Dict[str, Any]:
    return _request("GET", "/health", headers=_runtime_headers(), timeout=(CONNECT_TIMEOUT, 20))


@st.cache_data(ttl=10, show_spinner=False)
def _cached_health(runtime_fingerprint: str) -> Dict[str, Any]:
    return health()


def cached_health() -> Dict[str, Any]:
    return _cached_health(_runtime_header_fingerprint())


cached_health.clear = _cached_health.clear


def signup_user(email: str, password: str, full_name: str = "") -> Dict[str, Any]:
    return _request(
        "POST",
        "/auth/signup",
        json={
            "email": email.strip().lower(),
            "password": password,
            "full_name": full_name.strip() or None,
        },
        timeout=(CONNECT_TIMEOUT, 30),
    )


def forgot_password(email: str) -> Dict[str, Any]:
    return _request(
        "POST",
        "/auth/forgot-password",
        json={"email": email.strip().lower()},
        timeout=(CONNECT_TIMEOUT, 30),
    )


def reset_password(token: str, new_password: str) -> Dict[str, Any]:
    return _request(
        "POST",
        "/auth/reset-password",
        json={"token": token.strip(), "new_password": new_password},
        timeout=(CONNECT_TIMEOUT, 30),
    )


def verify_email(token: str) -> Dict[str, Any]:
    return _request(
        "POST",
        "/auth/verify-email",
        json={"token": token.strip()},
        timeout=(CONNECT_TIMEOUT, 30),
    )


def login_user(email: str, password: str) -> Dict[str, Any]:
    cached_list_collections.clear()
    clear_user_scoped_session_state()
    _clear_auth_tokens()
    st.session_state.auth_error = ""
    st.session_state.auth_notice_reason = ""
    _queue_browser_auth_clear()
    try:
        result = _request(
            "POST",
            "/auth/login",
            json={"email": email.strip().lower(), "password": password},
            timeout=(CONNECT_TIMEOUT, 30),
            max_attempts=1,
        )
    except Exception:
        raise
    access_token = _extract_token(result, "access_token")
    refresh_token = _extract_token(result, "refresh_token")
    user_payload = result.get("user") if isinstance(result.get("user"), dict) else {}
    st.session_state.auth_token = access_token
    st.session_state.auth_refresh_token = refresh_token
    st.session_state.auth_user = user_payload
    st.session_state.auth_error = ""
    st.session_state.auth_notice_reason = ""
    st.session_state.auth_checked_token = ""
    try:
        user = _request_once(
            "GET",
            "/auth/me",
            allow_auth_refresh=False,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(CONNECT_TIMEOUT, 30),
        )
    except ApiClientError as exc:
        logger.warning(
            "Post-login auth validation failed status=%s detail=%s",
            exc.status_code,
            str(exc)[:200],
        )
        clear_auth_session()
        raise ApiClientError("Unable to verify the authenticated session.", status_code=exc.status_code) from exc
    except Exception:
        raise
    st.session_state.auth_user = user
    st.session_state.auth_checked_token = access_token
    _queue_browser_auth_save()
    cached_list_collections.clear()
    return result


def refresh_access_token(show_expired_message: bool = True, clear_on_failure: bool = True) -> bool:
    refresh_token = str(st.session_state.get("auth_refresh_token", "")).strip()
    if not refresh_token:
        return False
    if st.session_state.get("_auth_refresh_failed_token") == refresh_token:
        return False
    try:
        request_kwargs = {"json": {"refresh_token": refresh_token}} if refresh_token else {}
        result = _request_once(
            "POST",
            "/auth/refresh",
            allow_auth_refresh=False,
            timeout=(CONNECT_TIMEOUT, 30),
            **request_kwargs,
        )
    except ApiClientError as exc:
        if exc.status_code in {401, 403}:
            st.session_state["_auth_refresh_failed_token"] = refresh_token
        if clear_on_failure:
            clear_auth_session("Session expired. Please sign in again." if show_expired_message else "")
        return False

    st.session_state.auth_token = _extract_token(result, "access_token")
    st.session_state.auth_refresh_token = _extract_token(result, "refresh_token") or refresh_token
    st.session_state.auth_user = result.get("user") or st.session_state.get("auth_user", {})
    st.session_state.auth_error = ""
    st.session_state.auth_notice_reason = ""
    st.session_state["_auth_refresh_failed_token"] = ""
    st.session_state.auth_checked_token = st.session_state.auth_token
    _queue_browser_auth_save()
    cached_list_collections.clear()
    return bool(st.session_state.auth_token)


def logout_user() -> None:
    st.session_state["_auth_logout_pending"] = True
    refresh_token = str(st.session_state.get("auth_refresh_token", "")).strip()
    try:
        request_kwargs = {"json": {"refresh_token": refresh_token}} if refresh_token else {}
        _request_once(
            "POST",
            "/auth/logout",
            allow_auth_refresh=False,
            timeout=(CONNECT_TIMEOUT, 30),
            **request_kwargs,
        )
    except ApiClientError:
        pass
    finally:
        clear_auth_session()


def clear_auth_session(message: str = "") -> None:
    cached_list_collections.clear()
    clear_user_scoped_session_state()
    clear_runtime_key_state()
    _queue_browser_auth_clear()
    _clear_auth_tokens()
    st.session_state["_login_in_progress"] = False
    st.session_state["_login_submit_consumed"] = False
    st.session_state.pop("_auth_panel_active_location", None)
    st.session_state.pop("_auth_panel_url", None)
    st.session_state["_auth_action_feedback_mode"] = ""
    st.session_state["_auth_action_feedback_kind"] = ""
    st.session_state["_auth_action_feedback_message"] = ""
    for key in list(st.session_state.keys()):
        if key.endswith(("_auth_login_email", "_auth_login_password", "_auth_login_password_visible")):
            st.session_state.pop(key, None)
    st.session_state.auth_error = message
    st.session_state.auth_notice_reason = "session_expired" if message == "Session expired. Please sign in again." else ""


def _clear_auth_tokens() -> None:
    st.session_state.auth_token = ""
    st.session_state.auth_refresh_token = ""
    st.session_state.auth_user = {}
    st.session_state.auth_checked_token = ""
    st.session_state["_auth_refresh_failed_token"] = ""


def _queue_browser_auth_save() -> None:
    access_token = _normalize_access_token(st.session_state.get("auth_token", ""))
    refresh_token = _normalize_access_token(st.session_state.get("auth_refresh_token", ""))
    user = st.session_state.get("auth_user") or {}
    st.session_state.pop("_auth_browser_pending_payload", None)
    if not access_token or not refresh_token or not user:
        return
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": user,
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    st.session_state["_auth_browser_pending_action"] = "save"
    st.session_state["_auth_browser_pending_payload"] = encoded
    st.session_state["_browser_auth_restore_loaded"] = True
    st.session_state["_auth_logout_pending"] = False


def _queue_browser_auth_clear() -> None:
    st.session_state["_auth_browser_pending_action"] = "clear"
    st.session_state.pop("_auth_browser_pending_payload", None)
    st.session_state["_browser_auth_restore_loaded"] = False


def _sync_browser_auth_storage() -> str:
    pending_action = st.session_state.pop("_auth_browser_pending_action", "")
    pending_payload = st.session_state.pop("_auth_browser_pending_payload", "")
    if pending_action == "clear":
        _browser_auth_storage("clear")
        st.session_state["_browser_auth_restore_loaded"] = True
        st.session_state["_auth_logout_pending"] = False
        return "clear"
    if pending_action == "save":
        if pending_payload:
            _browser_auth_storage("save", str(pending_payload))
            st.session_state["_browser_auth_restore_loaded"] = True
        return "save"
    return ""


def _restore_browser_auth_tokens() -> bool:
    result = _browser_auth_storage("load")
    if result is None:
        return False
    st.session_state["_browser_auth_restore_loaded"] = True
    raw_value = str((result or {}).get("payload", "") or "") if isinstance(result, dict) else ""
    if not raw_value:
        return True
    try:
        padded = raw_value + "=" * (-len(raw_value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception:
        _queue_browser_auth_clear()
        return True
    access_token = _extract_token(payload, "access_token")
    refresh_token = _extract_token(payload, "refresh_token")
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    if not access_token or not refresh_token:
        _queue_browser_auth_clear()
        return True
    st.session_state.auth_token = access_token
    st.session_state.auth_refresh_token = refresh_token
    st.session_state.auth_user = user or {}
    st.session_state.auth_checked_token = ""
    st.session_state.auth_error = ""
    st.session_state.auth_notice_reason = ""
    return True


def _browser_auth_storage(action: str, payload: str = "") -> dict | None:
    return _browser_auth_storage_component(
        action=action,
        payload=payload,
        default=None,
        key=f"browser_auth_storage_{action}",
    )


def clear_user_scoped_session_state() -> None:
    for key in USER_SCOPED_SESSION_KEYS:
        st.session_state.pop(key, None)


def get_current_user(clear_on_failure: bool = True) -> Dict[str, Any] | None:
    if not st.session_state.get("auth_token"):
        if clear_on_failure:
            st.session_state.auth_user = {}
            st.session_state.auth_error = ""
            st.session_state.auth_notice_reason = ""
            st.session_state.auth_checked_token = ""
        return None

    had_auth_state = bool(
        st.session_state.get("auth_token")
        or st.session_state.get("auth_refresh_token")
    )
    try:
        user = _request("GET", "/auth/me", timeout=(CONNECT_TIMEOUT, 30))
    except ApiClientError as exc:
        if clear_on_failure:
            clear_auth_session()
            st.session_state.auth_error = _friendly_auth_error(str(exc))
            st.session_state.auth_notice_reason = "session_expired" if had_auth_state else ""
        else:
            st.session_state.auth_user = {}
            st.session_state.auth_error = _friendly_auth_error(str(exc))
            st.session_state.auth_notice_reason = "session_expired" if had_auth_state else ""
        return None

    st.session_state.auth_user = user
    st.session_state.auth_error = ""
    st.session_state.auth_notice_reason = ""
    st.session_state.auth_checked_token = st.session_state.get("auth_token", "")
    return user


def restore_browser_auth_session() -> bool:
    auth_token = st.session_state.get("auth_token", "")
    auth_user = st.session_state.get("auth_user") or {}
    auth_checked_token = st.session_state.get("auth_checked_token", "")
    validated_session = bool(auth_token and auth_user and auth_checked_token == auth_token)
    pending_action = st.session_state.get("_auth_browser_pending_action", "")
    logout_pending = bool(st.session_state.get("_auth_logout_pending"))

    if validated_session and pending_action == "clear" and not logout_pending:
        _queue_browser_auth_save()

    browser_action = _sync_browser_auth_storage()
    if validated_session and not logout_pending:
        return True
    if browser_action == "clear":
        if st.session_state.get("auth_notice_reason") not in {"session_expired", "login_failed"}:
            st.session_state.auth_error = ""
            st.session_state.auth_notice_reason = ""
        return False
    if (
        auth_token
        and st.session_state.get("auth_user")
        and st.session_state.get("auth_checked_token") == auth_token
    ):
        return True
    if not st.session_state.get("auth_token"):
        if not _restore_browser_auth_tokens():
            st.stop()
    has_auth_state = bool(
        st.session_state.get("auth_token")
        or st.session_state.get("auth_refresh_token")
    )
    if not has_auth_state:
        if st.session_state.get("auth_notice_reason") not in {"session_expired", "login_failed"}:
            st.session_state.auth_error = ""
        return False

    logger.debug("Auth restore attempted: yes")
    user = get_current_user(clear_on_failure=False)
    if user:
        logger.debug("Auth restore result: success")
        _queue_browser_auth_save()
        return True
    if refresh_access_token(show_expired_message=False, clear_on_failure=False):
        restored = bool(get_current_user(clear_on_failure=False))
        logger.debug("Auth restore result: %s", "success" if restored else "failure")
        if restored:
            _queue_browser_auth_save()
        return restored

    logger.debug("Auth restore result: failure")
    clear_auth_session()
    return False


def upload_document(
    uploaded_file,
    collection_name: str,
    chunk_size: int,
    chunk_overlap: int,
    k: int,
    max_iterations: int,
    enable_grading: bool = True,
    enable_evaluation: bool = True,
    openai_api_key: str = "",
    tavily_api_key: str = "",
    embedding_provider: str = "",
    use_existing_collection: bool = False,
) -> Dict[str, Any]:
    cached_list_collections.clear()
    if not get_current_user(clear_on_failure=False):
        if not refresh_access_token(show_expired_message=False, clear_on_failure=False) or not get_current_user(clear_on_failure=False):
            raise ApiClientError("Invalid or expired authentication token.", status_code=401)
    files = {
        "file": (
            uploaded_file.name,
            uploaded_file.getvalue(),
            uploaded_file.type or "application/octet-stream",
        )
    }
    data = {
        "collection_name": collection_name,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "k": k,
        "max_iterations": max_iterations,
        "enable_grading": str(enable_grading).lower(),
        "enable_evaluation": str(enable_evaluation).lower(),
        "embedding_provider": embedding_provider or default_embedding_provider(),
        "use_existing_collection": str(use_existing_collection).lower(),
    }
    return _request(
        "POST",
        "/upload/document",
        files=files,
        data=data,
        headers=_runtime_headers(openai_api_key=openai_api_key, tavily_api_key=tavily_api_key),
        timeout=(CONNECT_TIMEOUT, 600),
    )


def chat(
    session_id: str,
    question: str,
    answer_length: str = "Medium: 180-250 words",
    allow_web_search: bool = False,
    collection_name: str = "",
) -> Dict[str, Any]:
    runtime_payload = runtime_secret_payload()
    return _request(
        "POST",
        "/chat",
        json={
            "session_id": session_id,
            "question": question,
            "answer_length": answer_length,
            "allow_web_search": allow_web_search,
            "collection_name": collection_name.strip(),
            "use_openai": runtime_payload["use_openai"],
            "force_local_stub": runtime_payload["force_local_stub"],
        },
        headers=_runtime_headers(),
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )


def chat_stream(
    session_id: str,
    question: str,
    answer_length: str = "Medium: 180-250 words",
    allow_web_search: bool = False,
    collection_name: str = "",
):
    url = f"{API_BASE_URL}/chat/stream"
    runtime_payload = runtime_secret_payload()
    response = None
    last_error = None
    for attempt in range(1):
        try:
            response = requests.post(
                url,
                headers=_backend_headers(_runtime_headers(), path="/chat/stream"),
                json={
                    "session_id": session_id,
                    "question": question,
                    "answer_length": answer_length,
                    "allow_web_search": allow_web_search,
                    "collection_name": collection_name.strip(),
                    "use_openai": runtime_payload["use_openai"],
                    "force_local_stub": runtime_payload["force_local_stub"],
                },
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                stream=True,
            )
            break
        except requests.Timeout as exc:
            last_error = ApiClientError("Streaming request timed out. Please try again.")
        except requests.ConnectionError as exc:
            last_error = ApiClientError("Backend is not reachable. Start FastAPI on port 8000.")
        except requests.RequestException as exc:
            last_error = ApiClientError(f"Streaming request failed: {exc}")
    if response is None:
        raise last_error or ApiClientError("Streaming request failed.")

    if _should_refresh_auth(response, "/chat/stream", True) and refresh_access_token(
        show_expired_message=False,
        clear_on_failure=False,
    ):
        response.close()
        response = requests.post(
            url,
            headers=_backend_headers(_runtime_headers(), path="/chat/stream"),
            json={
                "session_id": session_id,
                "question": question,
                "answer_length": answer_length,
                "allow_web_search": allow_web_search,
                "collection_name": collection_name.strip(),
                "use_openai": runtime_payload["use_openai"],
                "force_local_stub": runtime_payload["force_local_stub"],
            },
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            stream=True,
        )

    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiClientError(str(detail), status_code=response.status_code)

    event = None
    data_lines = []
    try:
        for raw_line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if raw_line is None:
                continue
            line = raw_line.strip()
            if not line:
                if event and data_lines:
                    payload = json.loads("\n".join(data_lines))
                    yield event, payload
                event = None
                data_lines = []
                continue
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
    except asyncio.CancelledError:
        logger.debug("Chat stream cancelled by the client.")
        raise
    except GeneratorExit:
        logger.debug("Chat stream closed by the client.")
        raise
    except (
        ConnectionResetError,
        BrokenPipeError,
        requests.ConnectionError,
        requests.exceptions.ChunkedEncodingError,
    ) as exc:
        logger.debug("Chat stream connection closed by the client: %s", exc)
        raise ApiClientDisconnect("Chat stream connection closed before completion.") from exc
    finally:
        response.close()


def list_collections() -> Dict[str, Any]:
    return _request("GET", "/collections/list", headers=_qdrant_headers(), timeout=(CONNECT_TIMEOUT, 30))


@st.cache_data(ttl=10, show_spinner=False)
def _cached_list_collections(runtime_fingerprint: str, auth_fingerprint: str) -> Dict[str, Any]:
    return list_collections()


def cached_list_collections() -> Dict[str, Any]:
    return _cached_list_collections(_runtime_header_fingerprint(), _auth_session_fingerprint())


cached_list_collections.clear = _cached_list_collections.clear


def get_collection_build_summary(collection_name: str) -> Dict[str, Any]:
    encoded_name = quote(collection_name.strip(), safe="")
    return _request(
        "GET",
        f"/collections/{encoded_name}/summary",
        timeout=(CONNECT_TIMEOUT, 30),
    )


def delete_collection(session_id: str) -> Dict[str, Any]:
    cached_list_collections.clear()
    return _request("DELETE", f"/collections/delete/{session_id}", headers=_qdrant_headers(), timeout=(CONNECT_TIMEOUT, 30))


def delete_collection_by_name(collection_name: str) -> Dict[str, Any]:
    cached_list_collections.clear()
    return _request(
        "DELETE",
        f"/collections/delete/by-name/{collection_name}",
        headers=_qdrant_headers(),
        timeout=(CONNECT_TIMEOUT, 30),
    )


def select_collection(collection_name: str, embedding_provider: str = "") -> Dict[str, Any]:
    return _request(
        "POST",
        "/collections/select",
        json={
            "collection_name": collection_name,
            "embedding_provider": embedding_provider or default_embedding_provider(),
        },
        headers=_qdrant_headers(),
        timeout=(COLLECTION_ACTIVATION_TIMEOUT, COLLECTION_ACTIVATION_TIMEOUT),
        max_attempts=2,
    )


def verify_collection_activation(collection_name: str) -> Dict[str, Any]:
    encoded_name = quote(collection_name.strip(), safe="")
    return _request(
        "GET",
        f"/collections/active/{encoded_name}",
        headers=_qdrant_headers(),
        timeout=(CONNECT_TIMEOUT, 15),
        max_attempts=1,
    )


def rebuild_bm25_index(collection_name: str) -> Dict[str, Any]:
    cached_list_collections.clear()
    return _request(
        "POST",
        f"/collections/bm25/rebuild/{collection_name}",
        headers=_qdrant_headers(),
        timeout=(CONNECT_TIMEOUT, 120),
    )


def vector_search(session_id: str, query: str) -> Dict[str, Any]:
    return _request(
        "POST",
        "/vector/search",
        json={
            "session_id": session_id,
            "query": query,
        },
        headers=_runtime_headers(),
        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
    )


def memory_stats() -> Dict[str, Any]:
    return _request("GET", "/collections/memory/stats", timeout=(CONNECT_TIMEOUT, 30))


@st.cache_data(ttl=10, show_spinner=False)
def _cached_memory_stats(auth_fingerprint: str) -> Dict[str, Any]:
    return memory_stats()


def cached_memory_stats() -> Dict[str, Any]:
    return _cached_memory_stats(_auth_session_fingerprint())


def get_audit_logs(
    limit: int = 50,
    event_type: str = "",
    status: str = "",
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": limit}
    if event_type.strip():
        params["event_type"] = event_type.strip()
    if status.strip() and status.strip().lower() != "all":
        params["status"] = status.strip().lower()
    if user_id is not None:
        params["user_id"] = user_id
    result = _request(
        "GET",
        "/admin/audit-logs",
        params=params,
        timeout=(CONNECT_TIMEOUT, 30),
    )
    return result if isinstance(result, list) else []


def get_admin_users() -> list[dict[str, Any]]:
    result = _request("GET", "/admin/users", timeout=(CONNECT_TIMEOUT, 30))
    return result if isinstance(result, list) else []


def get_admin_user(user_id: int) -> Dict[str, Any]:
    return _request("GET", f"/admin/users/{user_id}/status", timeout=(CONNECT_TIMEOUT, 30))


def update_admin_user_role(user_id: int, role: str) -> Dict[str, Any]:
    return _request(
        "PATCH",
        f"/admin/users/{user_id}/role",
        json={"role": role},
        timeout=(CONNECT_TIMEOUT, 30),
    )


def update_admin_user_status(user_id: int, is_active: bool) -> Dict[str, Any]:
    return _request(
        "PATCH",
        f"/admin/users/{user_id}/active",
        json={"is_active": is_active},
        timeout=(CONNECT_TIMEOUT, 30),
    )


def unlock_admin_user(user_id: int) -> Dict[str, Any]:
    return _request("POST", f"/admin/users/{user_id}/unlock", timeout=(CONNECT_TIMEOUT, 30))


def _runtime_headers(openai_api_key: str = "", tavily_api_key: str = "") -> dict[str, str]:
    payload = runtime_secret_payload()
    headers = {}
    runtime_openai_key = openai_api_key.strip() or str(payload.get("openai_api_key") or "").strip()
    runtime_tavily_key = tavily_api_key.strip() or str(payload.get("tavily_api_key") or "").strip()
    if runtime_openai_key:
        headers["X-Runtime-OpenAI-Key"] = runtime_openai_key
    headers["X-Use-OpenAI"] = "true" if payload.get("use_openai") else "false"
    headers["X-Force-Local-Stub"] = "true" if payload.get("force_local_stub") else "false"
    if runtime_tavily_key:
        headers["X-Runtime-Tavily-Api-Key"] = runtime_tavily_key
    return headers


def _runtime_header_fingerprint() -> str:
    payload = runtime_secret_payload()
    parts = []
    for key, value in sorted(payload.items()):
        safe_value = _safe_fingerprint_value(value)
        parts.append(f"{key}:{len(safe_value)}:{safe_value[-4:]}")
    return "|".join(parts)


def _auth_session_fingerprint() -> str:
    user = st.session_state.get("auth_user") or {}
    token = _safe_fingerprint_value(st.session_state.get("auth_token", ""))
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else "no-token"
    return "|".join(
        [
            f"id:{_safe_fingerprint_value(user.get('id'))}",
            f"email:{_safe_fingerprint_value(user.get('email')).strip().lower()}",
            f"role:{_safe_fingerprint_value(user.get('role'))}",
            f"superuser:{bool(user.get('is_superuser'))}",
            f"token:{token_hash}",
        ]
    )


def _safe_fingerprint_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _qdrant_headers() -> dict[str, str]:
    return _runtime_headers()


def _backend_headers(headers: Optional[dict[str, str]] = None, path: str = "") -> dict[str, str]:
    merged = dict(headers or {})
    if path.startswith("/auth/"):
        for key in list(merged):
            if key.lower().startswith("x-runtime-"):
                merged.pop(key, None)
    backend_api_key = get_secret_value("BACKEND_API_KEY")
    has_api_key_header = any(key.lower() == "x-api-key" for key in merged)
    if backend_api_key and not has_api_key_header:
        merged["X-API-Key"] = backend_api_key
    auth_token = _normalize_access_token(st.session_state.get("auth_token", ""))
    has_auth_header = any(key.lower() == "authorization" for key in merged)
    if auth_token and not has_auth_header:
        merged["Authorization"] = f"Bearer {auth_token}"
    return merged


def _extract_token(payload: Dict[str, Any], key: str) -> str:
    value = payload.get(key, "")
    if not isinstance(value, str):
        return ""
    return _normalize_access_token(value)


def _normalize_access_token(value: object) -> str:
    token = str(value or "").strip()
    while token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    return token


def _friendly_auth_error(message: str) -> str:
    lowered = message.lower()
    if "invalid" in lowered or "expired" in lowered or "401" in lowered:
        return "Session expired. Please sign in again."
    return "Could not refresh authentication. Please sign in again."


def _should_refresh_auth(
    response: requests.Response,
    path: str,
    allow_auth_refresh: bool,
) -> bool:
    if not allow_auth_refresh or response.status_code != 401:
        return False
    if _is_auth_lifecycle_path(path):
        return False
    return bool(st.session_state.get("auth_refresh_token"))


def _is_auth_lifecycle_path(path: str) -> bool:
    return path.startswith(
        (
            "/auth/login",
            "/auth/signup",
            "/auth/refresh",
            "/auth/logout",
            "/auth/forgot-password",
            "/auth/reset-password",
            "/auth/verify-email",
        )
    )
