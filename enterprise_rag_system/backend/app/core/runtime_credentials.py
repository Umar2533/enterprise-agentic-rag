from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.constants import CHAT_MODEL


SECRET_PATTERNS = (
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,})\b"),
    re.compile(r"\b(tvly-[A-Za-z0-9_\-]{8,})\b", re.IGNORECASE),
)


def mask_secret(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    prefix = value[:3] if len(value) >= 3 else value[:1]
    suffix = value[-4:] if len(value) > 4 else ""
    return f"{prefix}-****{suffix}" if suffix else f"{prefix}-****"


def redact_secrets_text(value: object) -> str:
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: mask_secret(match.group(1)), text)
    return text


@dataclass(frozen=True)
class RuntimeCredentials:
    openai_api_key: str = ""
    tavily_api_key: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    use_openai: bool = False
    force_local_stub: bool = False

    @classmethod
    def from_values(
        cls,
        openai_api_key: str = "",
        tavily_api_key: str = "",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        use_openai: bool = False,
        force_local_stub: bool = False,
    ) -> "RuntimeCredentials":
        return cls(
            openai_api_key=(openai_api_key or "").strip(),
            tavily_api_key=(tavily_api_key or "").strip(),
            qdrant_url=(qdrant_url or "").strip(),
            qdrant_api_key=(qdrant_api_key or "").strip(),
            use_openai=bool(use_openai),
            force_local_stub=bool(force_local_stub),
        )

    @property
    def effective_openai_api_key(self) -> str:
        settings = get_settings()
        return self.openai_api_key or (settings.openai_api_key or "").strip()

    @property
    def env_openai_api_key_present(self) -> bool:
        return bool((get_settings().openai_api_key or "").strip())

    @property
    def effective_tavily_api_key(self) -> str:
        settings = get_settings()
        return self.tavily_api_key or (settings.tavily_api_key or "").strip()

    @property
    def effective_qdrant_url(self) -> str:
        settings = get_settings()
        return self.qdrant_url or (settings.qdrant_url or "").strip()

    @property
    def effective_qdrant_api_key(self) -> str:
        settings = get_settings()
        return self.qdrant_api_key or (settings.qdrant_api_key or "").strip()

    def require_openai_api_key(self) -> str:
        key = self.effective_openai_api_key
        if not key:
            raise ValueError("OpenAI API key is required for this operation.")
        return key

    @property
    def llm_provider(self) -> str:
        if self.force_local_stub:
            return "local_stub"
        return "openai" if self.effective_openai_api_key else "local_stub"

    @property
    def local_test_mode_active(self) -> bool:
        settings = get_settings()
        return bool(settings.local_test_mode or self.llm_provider == "local_stub")

    @property
    def llm_model(self) -> str:
        return "deterministic context summarizer" if self.llm_provider == "local_stub" else CHAT_MODEL

    def require_chat_credentials(self) -> None:
        if self.llm_provider == "openai":
            self.require_openai_api_key()

    @property
    def runtime_openai_active(self) -> bool:
        return bool(self.openai_api_key and self.llm_provider == "openai")

    def as_local_stub(self) -> "RuntimeCredentials":
        return RuntimeCredentials.from_values(
            tavily_api_key=self.tavily_api_key,
            qdrant_url=self.qdrant_url,
            qdrant_api_key=self.qdrant_api_key,
            force_local_stub=True,
        )

    def should_fallback_to_local(self, error: object) -> bool:
        settings = get_settings()
        message = str(error).lower()
        error_type = type(error).__name__.lower()
        error_module = type(error).__module__.lower()
        openai_client_error = "openai" in error_module or error_type in {
            "apiconnectionerror",
            "apistatuserror",
            "authenticationerror",
            "ratelimiterror",
        }
        return bool(
            settings.openai_fallback_on_error
            and self.llm_provider == "openai"
            and (
                openai_client_error
                or any(marker in message for marker in ("429", "rate limit", "quota", "invalid", "api key", "authentication"))
            )
        )

    def require_tavily_api_key(self) -> str:
        key = self.effective_tavily_api_key
        if not key:
            raise ValueError("Tavily API key is required for web search.")
        return key

    def redact(self, value: object) -> str:
        text = redact_secrets_text(value)
        for secret in (
            self.openai_api_key,
            self.tavily_api_key,
            self.qdrant_api_key,
            self.effective_openai_api_key,
            self.effective_tavily_api_key,
            self.effective_qdrant_api_key,
        ):
            if secret:
                text = text.replace(secret, mask_secret(secret))
        return text
