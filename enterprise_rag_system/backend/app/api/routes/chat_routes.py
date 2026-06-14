import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_api_key
from app.core.rag_mode import require_rag_runtime
from app.core.runtime_credentials import RuntimeCredentials
from app.db.database import get_db
from app.models.user import User
from app.schemas.chat_schema import ChatRequest, ChatResponse, TraceStep
from app.services.collections.user_collection_service import get_user_collection_by_name, user_owns_session

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _safe_error_reason(credentials: RuntimeCredentials, error: object) -> str:
    reason = credentials.redact(error).replace("\r", " ").replace("\n", " ").strip()
    return reason[:180]


def _log_llm_selection(credentials: RuntimeCredentials, fallback_used: bool = False) -> None:
    logger.info(
        "Chat LLM selection runtime_key_present=%s env_key_present=%s selected_llm_provider=%s selected_model=%s fallback_used=%s",
        bool(credentials.openai_api_key),
        credentials.env_openai_api_key_present,
        credentials.llm_provider,
        credentials.llm_model,
        fallback_used,
    )


def _is_admin(user: User) -> bool:
    return user.is_superuser or user.role == "admin"


def _require_session_access(db: Session, user: User, session_id: str) -> None:
    if not session_id or (not _is_admin(user) and not user_owns_session(db, user.id, session_id)):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this collection.",
        )


def _require_collection_access(db: Session, user: User, collection_name: str | None) -> None:
    requested_collection = (collection_name or "").strip()
    if requested_collection and not _is_admin(user) and get_user_collection_by_name(db, user.id, requested_collection) is None:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this collection.",
        )


def _log_collection_context(request: ChatRequest) -> None:
    from app.services.rag_runtime import get_runtime_session

    runtime_session = get_runtime_session(request.session_id)
    runtime_collection = runtime_session.collection_name if runtime_session else ""
    requested_collection = (request.collection_name or "").strip()
    if requested_collection and runtime_collection and requested_collection != runtime_collection:
        logger.warning(
            "Chat collection mismatch session_id=%s requested_collection=%s runtime_collection=%s",
            request.session_id,
            requested_collection,
            runtime_collection,
        )
    else:
        logger.info(
            "Chat collection context session_id=%s collection=%s",
            request.session_id,
            runtime_collection or requested_collection or "unknown",
        )


def _runtime_credentials(
    request: ChatRequest,
    openai_api_key: str = "",
    tavily_api_key: str = "",
    qdrant_url: str = "",
    qdrant_api_key: str = "",
) -> RuntimeCredentials:
    return RuntimeCredentials.from_values(
        openai_api_key=openai_api_key or request.openai_api_key,
        tavily_api_key=tavily_api_key or request.tavily_api_key,
        qdrant_url=qdrant_url or request.qdrant_url,
        qdrant_api_key=qdrant_api_key or request.qdrant_api_key,
        use_openai=request.use_openai,
        force_local_stub=request.force_local_stub,
    )


def _stream_with_credentials(request: ChatRequest, credentials: RuntimeCredentials):
    from app.services.rag_runtime import stream_session_answer
    from app.services.vectordb.qdrant_service import qdrant_runtime_credentials

    try:
        with qdrant_runtime_credentials(
            credentials.effective_qdrant_url,
            credentials.effective_qdrant_api_key,
        ):
            yield from stream_session_answer(
                request.session_id,
                request.question,
                request.answer_length,
                request.allow_web_search,
                credentials,
                request.collection_name or "",
            )
    except asyncio.CancelledError:
        logger.debug("Chat stream cancelled by client session_id=%s", request.session_id)
        return
    except GeneratorExit:
        logger.debug("Chat stream closed by client session_id=%s", request.session_id)
        return
    except (ConnectionResetError, BrokenPipeError) as exc:
        logger.warning(
            "Chat stream client disconnected session_id=%s reason=%s",
            request.session_id,
            type(exc).__name__,
        )
        return


@router.post("", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
def chat(
    request: ChatRequest,
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_rag_runtime()

    from app.services.rag_runtime import ask_session
    from app.services.vectordb.qdrant_service import qdrant_runtime_credentials

    logger.info(
        "Chat request payload session_id=%s collection=%s question_length=%s answer_length=%s allow_web_search=%s",
        request.session_id,
        request.collection_name or "",
        len(request.question or ""),
        request.answer_length,
        request.allow_web_search,
    )
    _require_session_access(db, current_user, request.session_id)
    _require_collection_access(db, current_user, request.collection_name)
    _log_collection_context(request)
    credentials = _runtime_credentials(request, openai_api_key, tavily_api_key, qdrant_url, qdrant_api_key)
    _log_llm_selection(credentials)
    try:
        with qdrant_runtime_credentials(
            credentials.effective_qdrant_url,
            credentials.effective_qdrant_api_key,
        ):
            result = ask_session(
                request.session_id,
                request.question,
                request.answer_length,
                request.allow_web_search,
                credentials,
                request.collection_name or "",
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        if credentials.should_fallback_to_local(exc):
            fallback_credentials = credentials.as_local_stub()
            with qdrant_runtime_credentials(
                fallback_credentials.effective_qdrant_url,
                fallback_credentials.effective_qdrant_api_key,
            ):
                result = ask_session(
                    request.session_id,
                    request.question,
                    request.answer_length,
                    request.allow_web_search,
                    fallback_credentials,
                    request.collection_name or "",
                )
            result["llm_fallback_warning"] = "OpenAI unavailable; using local_stub for this answer."
            result["llm_fallback_status"] = "failed"
            result["error_reason"] = _safe_error_reason(credentials, exc)
            credentials = fallback_credentials
            _log_llm_selection(credentials, fallback_used=True)
        else:
            raise HTTPException(status_code=400, detail=credentials.redact(exc)) from exc
    except Exception as exc:
        if credentials.should_fallback_to_local(exc):
            fallback_credentials = credentials.as_local_stub()
            with qdrant_runtime_credentials(
                fallback_credentials.effective_qdrant_url,
                fallback_credentials.effective_qdrant_api_key,
            ):
                result = ask_session(
                    request.session_id,
                    request.question,
                    request.answer_length,
                    request.allow_web_search,
                    fallback_credentials,
                    request.collection_name or "",
                )
            result["llm_fallback_warning"] = "OpenAI unavailable; using local_stub for this answer."
            result["llm_fallback_status"] = "failed"
            result["error_reason"] = _safe_error_reason(credentials, exc)
            credentials = fallback_credentials
            _log_llm_selection(credentials, fallback_used=True)
        else:
            raise HTTPException(status_code=500, detail=f"Chat failed: {credentials.redact(exc)}") from exc

    return ChatResponse(
        success=True,
        answer=result.get("answer", "No answer generated."),
        search_type=result.get("search_type", "vectorstore"),
        evaluation=result.get("evaluation"),
        iteration_count=result.get("iteration_count", 1),
        retrieved_docs_count=result.get("retrieved_docs_count", 0),
        web_results_count=result.get("web_results_count", 0),
        confidence_level=result.get("confidence_level", "unknown"),
        retrieval_mode=result.get("retrieval_mode", "unknown"),
        retrieval_warning=result.get("retrieval_warning", ""),
        llm_provider=result.get("llm_provider", credentials.llm_provider),
        llm_model=result.get("llm_model", credentials.llm_model),
        runtime_openai_active=bool(result.get("runtime_openai_active", credentials.runtime_openai_active)),
        llm_fallback_warning=result.get("llm_fallback_warning", ""),
        llm_fallback_status=result.get("llm_fallback_status", ""),
        error_reason=result.get("error_reason", ""),
        web_search_used=bool(result.get("web_search_used", False)),
        web_search_available=bool(result.get("web_search_available", False)),
        web_search_requires_approval=bool(result.get("web_search_requires_approval", False)),
        trace_steps=result.get("trace_steps") or result.get("trace", []),
        trace=[TraceStep(**step) for step in result.get("trace", [])],
        sources=result.get("sources", []),
    )


@router.post("/stream", dependencies=[Depends(require_api_key)])
def chat_stream(
    request: ChatRequest,
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Api-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_rag_runtime()

    _require_session_access(db, current_user, request.session_id)
    _require_collection_access(db, current_user, request.collection_name)
    _log_collection_context(request)
    credentials = _runtime_credentials(request, openai_api_key, tavily_api_key, qdrant_url, qdrant_api_key)
    _log_llm_selection(credentials)
    return StreamingResponse(
        _stream_with_credentials(request, credentials),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
