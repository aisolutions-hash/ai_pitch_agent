"""LLM provider adapters.

Providers are intentionally thin and degrade gracefully: an unavailable local
runtime or a failed cloud call raises, and the router moves to the next provider
in the fallback chain. ``EchoProvider`` keeps the pipeline and tests working
with zero network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from ..config import settings


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    fallback_used: bool = False


class LLMProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def generate(
        self,
        *,
        prompt: str,
        system: str = "",
        model: str,
        max_output_tokens: int,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMResult: ...


class EchoProvider:
    """Deterministic offline provider used as the final fallback and in tests."""

    name = "echo"

    @property
    def available(self) -> bool:
        return True

    def generate(
        self,
        *,
        prompt: str,
        system: str = "",
        model: str,
        max_output_tokens: int,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMResult:
        started = monotonic()
        text = '{"result": "echo"}' if json_mode else "[echo] " + (prompt or "")[:200]
        return LLMResult(
            text=text,
            provider=self.name,
            model=model or "echo",
            input_tokens=estimate_tokens(system + prompt),
            output_tokens=estimate_tokens(text),
            latency_ms=int((monotonic() - started) * 1000),
        )


class OllamaProvider:
    """Local small-language-model runtime (https://ollama.com)."""

    name = "ollama"

    def __init__(self, base_url: str | None = None, default_model: str | None = None):
        self.base_url = (base_url or settings.LLM_LOCAL_BASE_URL).rstrip("/")
        self.default_model = default_model or settings.LLM_LOCAL_MODEL

    @property
    def available(self) -> bool:
        return bool(self.base_url)

    def generate(
        self,
        *,
        prompt: str,
        system: str = "",
        model: str,
        max_output_tokens: int,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMResult:
        import httpx

        started = monotonic()
        payload = {
            "model": model or self.default_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "format": "json" if json_mode else None,
            "options": {"temperature": temperature, "num_predict": max_output_tokens},
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            response = client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        text = data.get("response", "")
        return LLMResult(
            text=text,
            provider=self.name,
            model=data.get("model", model or self.default_model),
            input_tokens=int(data.get("prompt_eval_count") or estimate_tokens(system + prompt)),
            output_tokens=int(data.get("eval_count") or estimate_tokens(text)),
            latency_ms=int((monotonic() - started) * 1000),
        )


class GeminiProvider:
    """Google Gemini via the Generative Language REST API."""

    name = "gemini"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.GEMINI_API_KEY

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        *,
        prompt: str,
        system: str = "",
        model: str,
        max_output_tokens: int,
        temperature: float = 0.2,
        json_mode: bool = False,
    ) -> LLMResult:
        import httpx

        started = monotonic()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json" if json_mode else "text/plain",
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        with httpx.Client(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            response = client.post(url, params={"key": self.api_key}, json=body)
            response.raise_for_status()
            data = response.json()
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        text = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata", {})
        return LLMResult(
            text=text,
            provider=self.name,
            model=model,
            input_tokens=int(usage.get("promptTokenCount") or estimate_tokens(system + prompt)),
            output_tokens=int(usage.get("candidatesTokenCount") or estimate_tokens(text)),
            latency_ms=int((monotonic() - started) * 1000),
        )


class GemmaProvider(GeminiProvider):
    """Gemma model via the same Generative Language API surface."""

    name = "gemma"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        super().__init__(api_key=api_key)
        self.default_model = model or settings.LLM_GEMMA_MODEL
