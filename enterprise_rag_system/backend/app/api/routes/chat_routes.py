import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_api_key
from app.core.config import get_settings
from app.core.rag_mode import require_render_free_openai
from app.core.runtime_credentials import RuntimeCredentials
from app.db.database import get_db
from app.models.user import User
from app.models.user_collection import UserCollection
from app.schemas.chat_schema import ChatRequest, ChatResponse, TraceStep
from app.services.collections.user_collection_service import (
    get_user_collection_by_name,
    get_user_collection_by_session,
    user_owns_session,
)
from app.services.render_free_openai_chat import (
    RenderFreeChatError,
    chat_render_free_openai,
    render_free_chat_events,
)

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


def _chat_collection(db: Session, user: User, request: ChatRequest) -> UserCollection | None:
    collection = get_user_collection_by_session(
        db,
        request.session_id,
        None if _is_admin(user) else user.id,
    )
    if collection is None and request.collection_name:
        collection = get_user_collection_by_name(db, user.id, request.collection_name.strip())
    return collection


def _ensure_collection_runtime_session(
    request: ChatRequest,
    credentials: RuntimeCredentials,
    collection: UserCollection | None,
) -> None:
    if collection is None:
        return

    from app.services.rag_runtime import get_runtime_session, select_existing_collection
    from app.services.vectordb.qdrant_service import qdrant_runtime_credentials

    session = get_runtime_session(request.session_id)
    embedding_provider = (
        (collection.embedding_provider or "").strip()
        or (session.embedding_provider if session is not None else "")
        or "huggingface"
    )
    embedding_model = (collection.embedding_model or "").strip() or (
        session.embedding_model if session is not None else None
    )
    vector_size = collection.vector_size or (session.vector_size if session is not None else None)
    if (
        session is not None
        and session.collection_name == collection.collection_name
        and session.embedding_provider == embedding_provider
        and (not embedding_model or session.embedding_model == embedding_model)
        and (not vector_size or session.vector_size == vector_size)
    ):
        return
    with qdrant_runtime_credentials(
        credentials.effective_qdrant_url,
        credentials.effective_qdrant_api_key,
    ):
        select_existing_collection(
            session_id=request.session_id,
            collection_name=collection.collection_name,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            vector_size=vector_size,
            credentials=credentials,
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
    if get_settings().render_free_mvp:
        if not (openai_api_key or "").strip():
            return RuntimeCredentials.from_values(
                tavily_api_key=tavily_api_key,
                qdrant_url=qdrant_url,
                qdrant_api_key=qdrant_api_key,
            )
        return RuntimeCredentials.from_values(
            openai_api_key=openai_api_key,
            use_openai=True,
        )
    return RuntimeCredentials.from_values(
        openai_api_key=openai_api_key or request.openai_api_key,
        tavily_api_key=tavily_api_key or request.tavily_api_key,
        qdrant_url=qdrant_url or request.qdrant_url,
        qdrant_api_key=qdrant_api_key or request.qdrant_api_key,
        use_openai=request.use_openai,
        force_local_stub=request.force_local_stub,
    )


def _render_free_result(
    request: ChatRequest,
    openai_api_key: str,
    collection: UserCollection,
) -> dict:
    try:
        return chat_render_free_openai(
            collection_name=collection.collection_name,
            question=request.question,
            answer_length=request.answer_length,
            openai_api_key=openai_api_key.strip(),
        )
    except RenderFreeChatError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    collection = _chat_collection(db, current_user, request)
    stored_provider = (collection.embedding_provider or "").strip().lower() if collection is not None else ""
    if get_settings().render_free_mvp:
        collection_found = collection is not None
        logger.warning(
            "Render Free chat debug collection_name=%s session_id=%s "
            "user_id=%s user_email=%s user_role=%s "
            "user_collection_found=%s requested_provider=%s stored_provider=%s effective_branch=%s",
            request.collection_name or "",
            request.session_id,
            current_user.id,
            current_user.email,
            current_user.role,
            collection_found,
            "<not_in_chat_request>",
            stored_provider or "<missing>",
            "openai_byok" if stored_provider == "openai" else "metadata_runtime",
        )
        if (
            (openai_api_key or "").strip()
            and stored_provider not in {"openai", "cloudflare"}
        ):
            disabled_branch = (
                "user_collection_not_found"
                if not collection_found
                else "collection_embedding_provider_not_openai"
            )
            logger.warning(
                "Render Free chat returning disabled 503 branch=%s "
                "collection_name=%s session_id=%s user_id=%s",
                disabled_branch,
                request.collection_name or "",
                request.session_id,
                current_user.id,
            )
    require_render_free_openai(
        openai_api_key,
        stored_provider,
    )
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
    if (
        get_settings().render_free_mvp
        and collection is not None
        and stored_provider == "openai"
        and (openai_api_key or "").strip()
    ):
        credentials = _runtime_credentials(request, openai_api_key)
        _log_llm_selection(credentials)
        result = _render_free_result(request, openai_api_key, collection)
        return ChatResponse(
            success=True,
            answer=result["answer"],
            search_type=result["search_type"],
            evaluation=result["evaluation"],
            iteration_count=result["iteration_count"],
            retrieved_docs_count=result["retrieved_docs_count"],
            web_results_count=0,
            confidence_level=result["confidence_level"],
            retrieval_mode=result["retrieval_mode"],
            retrieval_warning=result["retrieval_warning"],
            llm_provider="openai",
            llm_model=result["llm_model"],
            runtime_openai_active=True,
            llm_fallback_status="not_used",
            web_search_used=False,
            web_search_available=False,
            web_search_requires_approval=False,
            trace_steps=result["trace_steps"],
            trace=[TraceStep(**step) for step in result["trace"]],
            sources=result["sources"],
        )

    from app.services.rag_runtime import ask_session
    from app.services.vectordb.qdrant_service import qdrant_runtime_credentials

    runtime_openai_key = "" if get_settings().render_free_mvp and stored_provider != "openai" else openai_api_key
    credentials = _runtime_credentials(request, runtime_openai_key, tavily_api_key, qdrant_url, qdrant_api_key)
    _ensure_collection_runtime_session(request, credentials, collection)
    _log_collection_context(request)
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
        if not get_settings().render_free_mvp and credentials.should_fallback_to_local(exc):
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
        if not get_settings().render_free_mvp and credentials.should_fallback_to_local(exc):
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
    openai_api_key: str = Header("", alias="X-Runtime-OpenAI-Key"),
    tavily_api_key: str = Header("", alias="X-Runtime-Tavily-Api-Key"),
    qdrant_url: str = Header("", alias="X-Runtime-Qdrant-Url"),
    qdrant_api_key: str = Header("", alias="X-Runtime-Qdrant-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    collection = _chat_collection(db, current_user, request)
    stored_provider = (collection.embedding_provider or "").strip().lower() if collection is not None else ""
    require_render_free_openai(
        openai_api_key,
        stored_provider,
    )

    _require_session_access(db, current_user, request.session_id)
    _require_collection_access(db, current_user, request.collection_name)
    if (
        get_settings().render_free_mvp
        and collection is not None
        and stored_provider == "openai"
        and (openai_api_key or "").strip()
    ):
        credentials = _runtime_credentials(request, openai_api_key)
        _log_llm_selection(credentials)
        result = _render_free_result(request, openai_api_key, collection)
        return StreamingResponse(
            render_free_chat_events(result),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    runtime_openai_key = "" if get_settings().render_free_mvp and stored_provider != "openai" else openai_api_key
    credentials = _runtime_credentials(request, runtime_openai_key, tavily_api_key, qdrant_url, qdrant_api_key)
    _ensure_collection_runtime_session(request, credentials, collection)
    _log_collection_context(request)
    _log_llm_selection(credentials)
    return StreamingResponse(
        _stream_with_credentials(request, credentials),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
