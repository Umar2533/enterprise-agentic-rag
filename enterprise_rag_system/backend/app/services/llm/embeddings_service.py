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


DEFAULT_VECTOR_SIZES = {
    DEFAULT_EMBEDDING_PROVIDER: 384,
    "cloudflare": 384,
    "openai": 1536,
}
CLOUDFLARE_VECTOR_SIZES = {
    "@cf/baai/bge-small-en-v1.5": 384,
}


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


class CloudflareEmbeddingsLite(Embeddings):
    def __init__(self, account_id: str, api_token: str, model: str):
        import requests

        self._requests = requests
        self._account_id = account_id.strip()
        self._api_token = api_token.strip()
        self._model = model.strip()
        if not self._account_id:
            raise UnsupportedEmbeddingProviderError("Cloudflare account id is not configured.")
        if not self._api_token:
            raise UnsupportedEmbeddingProviderError("Cloudflare API token is not configured.")
        if not self._model:
            raise UnsupportedEmbeddingProviderError("Cloudflare embedding model is not configured.")

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        payload = {"text": [str(text) for text in texts]}
        response = self._requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai/run/{self._model}",
            headers={
                "Authorization": f"Bearer {self._api_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Cloudflare embeddings request failed: {response.status_code} {response.text}")
        data = response.json()
        vectors = data.get("result", {}).get("data")
        if not isinstance(vectors, list):
            raise RuntimeError("Cloudflare embeddings response did not include result.data.")
        return [_float_vector(vector) for vector in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _float_vector(vector: object) -> list[float]:
    if not isinstance(vector, list):
        raise RuntimeError("Cloudflare embeddings response contained an invalid vector.")
    return [float(value) for value in vector]


def normalize_embedding_provider(provider: str | None) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in {"", "unknown", "none", "null"}:
        return DEFAULT_EMBEDDING_PROVIDER
    if normalized in {"huggingface", "sentence-transformers", "sentence_transformers"}:
        return DEFAULT_EMBEDDING_PROVIDER
    if normalized == "openai":
        return "openai"
    if normalized == "cloudflare":
        return "cloudflare"
    if normalized == "gemini":
        return "gemini"

    supported = ", ".join(SUPPORTED_EMBEDDING_PROVIDERS)
    raise UnsupportedEmbeddingProviderError(
        f"Unsupported embedding provider: {provider}. Supported values: {supported}"
    )


def embedding_model_for_provider(provider: str, model: str | None = None) -> str:
    provider = normalize_embedding_provider(provider)
    requested_model = (model or "").strip()
    if requested_model:
        return requested_model
    if provider == "openai":
        return OPENAI_EMBEDDING_MODEL
    if provider == "cloudflare":
        return (get_settings().cloudflare_embedding_model or "").strip()
    if provider == "gemini":
        raise UnsupportedEmbeddingProviderError("Gemini embeddings not implemented yet.")
    return EMBEDDING_MODEL


def embedding_vector_size_for_provider(provider: str, model: str | None = None) -> int | None:
    provider = normalize_embedding_provider(provider)
    embedding_model = embedding_model_for_provider(provider, model)
    if provider == "cloudflare":
        return CLOUDFLARE_VECTOR_SIZES.get(embedding_model, DEFAULT_VECTOR_SIZES["cloudflare"])
    return DEFAULT_VECTOR_SIZES.get(provider)


@lru_cache(maxsize=4)
def _huggingface_embeddings():
    settings = get_settings()
    configured_provider = normalize_embedding_provider(settings.embedding_provider)
    if not settings.allow_local_embeddings or configured_provider != DEFAULT_EMBEDDING_PROVIDER:
        raise UnsupportedEmbeddingProviderError(
            "Local HuggingFace embeddings are disabled for this environment. "
            "Set ALLOW_LOCAL_EMBEDDINGS=true and EMBEDDING_PROVIDER=huggingface, "
            "then install backend/requirements-dev.txt to use local embeddings."
        )

    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError as exc:
        raise UnsupportedEmbeddingProviderError(
            "Local HuggingFace embeddings require optional development packages. "
            "Install them with: pip install -r backend/requirements-dev.txt"
        ) from exc

    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_embeddings(
    provider: str = DEFAULT_EMBEDDING_PROVIDER,
    credentials: RuntimeCredentials | None = None,
    model: str | None = None,
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
        embedding_model = embedding_model_for_provider(provider, model)
        if get_settings().render_free_mvp:
            return OpenAIEmbeddingsLite(
                api_key=credentials.require_openai_api_key(),
                model=embedding_model,
            )
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            api_key=credentials.require_openai_api_key(),
            model=embedding_model,
        )
    if provider == "cloudflare":
        settings = get_settings()
        return CloudflareEmbeddingsLite(
            account_id=settings.cloudflare_account_id,
            api_token=settings.cloudflare_api_token,
            model=embedding_model_for_provider(provider, model),
        )
    if provider == "gemini":
        raise UnsupportedEmbeddingProviderError("Gemini embeddings not implemented yet.")
    raise UnsupportedEmbeddingProviderError(f"Unsupported embedding provider: {provider}")
