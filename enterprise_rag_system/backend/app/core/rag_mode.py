from fastapi import HTTPException

from app.core.config import get_settings


RAG_RUNTIME_DISABLED_MESSAGE = (
    "RAG runtime is disabled on Render Free. Use OpenAI BYOK MVP mode or upgrade the backend instance."
)


def require_rag_runtime() -> None:
    if get_settings().render_free_mvp:
        raise HTTPException(status_code=503, detail=RAG_RUNTIME_DISABLED_MESSAGE)
