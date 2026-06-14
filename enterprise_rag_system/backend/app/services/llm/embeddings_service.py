from functools import lru_cache
from typing import Iterable

from langchain_core.embeddings import Embeddings

from app.core.constants import (
    DEFAULT_EMBEDDING_PROVIDER,
    EMBEDDING_MODEL,
    OPENAI_EMBEDDING_MODEL,
    SUPPORTED_EMBEDDING_PROVIDERS,
)
from app.core.config import get_settings
from app.core.runtime_credentials import RuntimeCredentials


class UnsupportedEmbeddingProviderError(ValueError):
    pass


class OpenAIEmbeddingsLite(Embeddings):
    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=self._model,
            input=list(texts),
        )
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


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
    from langchain_huggingface import HuggingFaceEmbeddings

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
        if get_settings().render_free_mvp:
            raise UnsupportedEmbeddingProviderError(
                "HuggingFace embeddings are disabled on Render Free."
            )
        return _huggingface_embeddings()
    if provider == "openai":
        credentials = credentials or RuntimeCredentials()
        if get_settings().render_free_mvp:
            return OpenAIEmbeddingsLite(
                api_key=credentials.require_openai_api_key(),
                model=OPENAI_EMBEDDING_MODEL,
            )
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            api_key=credentials.require_openai_api_key(),
            model=OPENAI_EMBEDDING_MODEL,
        )
    raise UnsupportedEmbeddingProviderError(f"Unsupported embedding provider: {provider}")
