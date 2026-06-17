import re
import logging
from collections import Counter
from types import SimpleNamespace
from urllib.parse import urlparse

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core.config import get_settings
from app.core.constants import CHAT_MODEL
from app.core.rag_mode import MISSING_RUNTIME_OPENAI_KEY_MESSAGE
from app.core.runtime_credentials import RuntimeCredentials


logger = logging.getLogger(__name__)
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _chat_messages(prompt_value) -> list[dict[str, str]]:
    messages = getattr(prompt_value, "messages", None)
    if not isinstance(messages, (list, tuple)):
        return [{"role": "user", "content": str(prompt_value)}]

    converted: list[dict[str, str]] = []
    for message in messages:
        role = str(getattr(message, "type", "") or getattr(message, "role", "")).lower()
        if role in {"human", "user"}:
            role = "user"
        elif role in {"ai", "assistant"}:
            role = "assistant"
        elif role != "system":
            role = "user"
        converted.append({"role": role, "content": str(getattr(message, "content", message))})
    return converted or [{"role": "user", "content": str(prompt_value)}]


class OpenAIChatModelLite:
    def __init__(
        self,
        api_key: str,
        model: str,
        streaming: bool,
        base_url: str | None = None,
        provider: str = "openai",
    ):
        from openai import OpenAI

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self._streaming = streaming
        self._base_url = base_url or ""
        self._provider = provider
        self._log_client("constructed")

    def invoke(self, prompt: str):
        self._log_and_validate_client()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=_chat_messages(prompt),
            temperature=0,
        )
        return SimpleNamespace(content=response.choices[0].message.content or "")

    def stream(self, prompt: str):
        self._log_and_validate_client()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=_chat_messages(prompt),
            temperature=0,
            stream=True,
        )
        for chunk in response:
            yield SimpleNamespace(content=chunk.choices[0].delta.content or "")

    def _log_and_validate_client(self) -> None:
        self._log_client("before_call")
        if self._provider == "groq" and _base_url_host(self._base_url) != "api.groq.com":
            raise RuntimeError("Groq provider selected but client base_url is not Groq")

    def _log_client(self, event: str) -> None:
        base_url_host = _base_url_host(self._base_url)
        logger.warning(
            "LLM client %s class=%s provider=%s model=%s base_url_host=%s",
            event,
            self.__class__.__name__,
            self._provider,
            self._model,
            base_url_host,
        )


def _base_url_host(base_url: str | None) -> str:
    if not base_url:
        return "default_openai"
    return urlparse(base_url).hostname or "default_openai"


def _settings_llm_provider(settings) -> str:
    provider = (
        str(getattr(settings, "effective_llm_provider", "") or settings.llm_provider or "auto")
        .strip()
        .lower()
    )
    if provider == "auto":
        if (settings.openai_api_key or "").strip():
            return "openai"
        if (settings.groq_api_key or "").strip():
            return "groq"
        return "local_stub"
    if provider == "groq" and not (settings.groq_api_key or "").strip():
        return "local_stub"
    if provider == "openai" and not (settings.openai_api_key or "").strip():
        return "openai"
    return provider


_STOP_WORDS = {
    "about", "after", "also", "and", "are", "been", "before", "being", "between",
    "but", "can", "content", "context", "could", "document", "documents", "for",
    "from", "has", "have", "into", "its", "more", "not", "only", "other", "our",
    "retrieved", "section", "source", "that", "the", "their", "there", "these",
    "they", "this", "through", "using", "was", "were", "what", "when", "where",
    "which", "while", "with", "would", "your",
}


def _prompt_text(prompt_value) -> str:
    messages = getattr(prompt_value, "messages", prompt_value)
    if not isinstance(messages, (list, tuple)):
        messages = [messages]
    return "\n".join(str(getattr(message, "content", message)) for message in messages)


def _extract_context(text: str) -> str:
    match = re.search(r"\nContext:\s*(.*?)\n\nQuestion:\s*", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_chunks(context: str) -> list[str]:
    chunks = []
    for block in re.split(r"\n\s*---\s*\n", context):
        content_match = re.search(r"\ncontent:\s*\n?(.*)", block, flags=re.IGNORECASE | re.DOTALL)
        content = content_match.group(1).strip() if content_match else block.strip()
        if content:
            chunks.append(content)
    return chunks


def _summary_sentences(chunks: list[str], limit: int = 5) -> list[str]:
    sentences = []
    seen = set()
    for chunk in chunks:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", chunk):
            cleaned = re.sub(r"\s+", " ", sentence).strip(" -\t")
            key = cleaned.lower()
            if len(cleaned) < 24 or key in seen:
                continue
            seen.add(key)
            sentences.append(cleaned)
            if len(sentences) >= limit:
                return sentences
    return sentences


def _key_topics(chunks: list[str], limit: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", " ".join(chunks).lower())
    counts = Counter(word for word in words if word not in _STOP_WORDS)
    return [word.replace("_", " ").title() for word, _ in counts.most_common(limit)]


def _extractive_document_answer(context: str) -> str:
    chunks = _extract_chunks(context)
    if not chunks:
        return "No relevant content was found in the active collection."

    sentences = _summary_sentences(chunks)
    topics = _key_topics(chunks)
    overview = " ".join(sentences[:3]) or re.sub(r"\s+", " ", chunks[0]).strip()[:900]
    key_points = sentences[3:5] or sentences[: min(3, len(sentences))]
    topic_text = ", ".join(topics) if topics else "No distinct topics extracted"
    points_text = "\n".join(f"- {sentence}" for sentence in key_points)
    if not points_text:
        points_text = f"- {overview}"

    return (
        "Document overview:\n"
        f"{overview}\n\n"
        "Key topics:\n"
        f"{topic_text}\n\n"
        "Key points from retrieved content:\n"
        f"{points_text}\n\n"
        f"Sources used: {len(chunks)}\n"
        f"Retrieved chunks: {len(chunks)}"
    )


def _local_stub_response(prompt_value) -> AIMessage:
    text = _prompt_text(prompt_value)
    lowered = text.lower()
    if "semantic scope gate" in lowered or "collection relevance" in lowered:
        return AIMessage(content="related")
    if "answer quality evaluator" in lowered:
        return AIMessage(content="good")
    if "relevance grader" in lowered:
        return AIMessage(content="yes")
    return AIMessage(content=_extractive_document_answer(_extract_context(text)))


def get_chat_model(streaming: bool = True, credentials: RuntimeCredentials | None = None):
    credentials = credentials or RuntimeCredentials()
    settings = get_settings()
    provider = _settings_llm_provider(settings)
    model = settings.groq_model if provider == "groq" else CHAT_MODEL
    base_url = GROQ_BASE_URL if provider == "groq" else None
    logger.warning(
        "LLM model selection runtime_key_present=%s env_key_present=%s groq_key_present=%s provider=%s model=%s base_url_host=%s fallback_used=%s",
        bool(credentials.openai_api_key),
        credentials.env_openai_api_key_present,
        credentials.env_groq_api_key_present,
        provider,
        model if provider != "local_stub" else "deterministic context summarizer",
        _base_url_host(base_url),
        provider == "local_stub",
    )
    if provider == "local_stub":
        if get_settings().render_free_mvp:
            raise ValueError(MISSING_RUNTIME_OPENAI_KEY_MESSAGE)
        return RunnableLambda(_local_stub_response)
    if provider == "groq":
        return OpenAIChatModelLite(
            api_key=(settings.groq_api_key or "").strip(),
            model=model,
            streaming=streaming,
            base_url=base_url,
            provider="groq",
        )
    if settings.render_free_mvp:
        return OpenAIChatModelLite(
            api_key=credentials.require_openai_api_key(),
            model=CHAT_MODEL,
            streaming=streaming,
            provider="openai",
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=credentials.require_openai_api_key(),
        model=CHAT_MODEL,
        temperature=0,
        streaming=streaming,
    )
