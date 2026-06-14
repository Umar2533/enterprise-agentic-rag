from fastapi import HTTPException

from app.core.config import get_settings


RAG_RUNTIME_DISABLED_MESSAGE = (
    "RAG runtime is disabled on Render Free. Use OpenAI BYOK MVP mode or upgrade the backend instance."
)
MISSING_RUNTIME_OPENAI_KEY_MESSAGE = (
    "Add your OpenAI API key in Settings to use this feature."
)


def require_rag_runtime() -> None:
    if get_settings().render_free_mvp:
        raise HTTPException(status_code=503, detail=RAG_RUNTIME_DISABLED_MESSAGE)


def require_render_free_openai(runtime_openai_key: str, embedding_provider: str) -> None:
    if not get_settings().render_free_mvp:
        return
    if not (runtime_openai_key or "").strip():
        raise HTTPException(status_code=400, detail=MISSING_RUNTIME_OPENAI_KEY_MESSAGE)
    if (embedding_provider or "").strip().lower() != "openai":
        raise HTTPException(status_code=503, detail=RAG_RUNTIME_DISABLED_MESSAGE)
