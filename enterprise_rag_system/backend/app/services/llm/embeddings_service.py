from functools import lru_cache

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import OpenAIEmbeddings

from app.core.constants import (
    DEFAULT_EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    OPENAI_EMBEDDING_MODEL,
    SUPPORTED_EMBEDDING_PROVIDERS,
)
from app.core.runtime_credentials import RuntimeCredentials


class UnsupportedEmbeddingProviderError(ValueError):
    pass


def normalize_embedding_provider(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in {"", "unknown", "none", "null"}:
        return DEFAULT_EMBEDDING_PROVIDER
    if normalized in {"huggingface", "sentence-transformers", "sentence_transformers"}:
        return DEFAULT_EMBEDDING_PROVIDER
    if normalized == "openai":
        return "openai"

    supported = ", ".join(SUPPORTED_EMBEDDING_PROVIDERS)
    raise UnsupportedEmbeddingProviderError(
        f"Unsupported embedding provider: {provider}. Supported values: {supported}"
    )


@lru_cache(maxsize=4)
def _huggingface_embeddings():
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_embeddings(
    provider: str = DEFAULT_EMBEDDING_PROVIDER,
    credentials: RuntimeCredentials | None = None,
):
    provider = normalize_embedding_provider(provider)
    if provider == DEFAULT_EMBEDDING_PROVIDER:
        return _huggingface_embeddings()
    if provider == "openai":
        credentials = credentials or RuntimeCredentials()
        return OpenAIEmbeddings(
            api_key=credentials.require_openai_api_key(),
            model=OPENAI_EMBEDDING_MODEL,
        )
    raise UnsupportedEmbeddingProviderError(f"Unsupported embedding provider: {provider}")
