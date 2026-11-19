"""Minimal OpenAI-compatible chat-completions client.

Supports free-tier endpoints that expose the OpenAI chat API (Groq by default,
plus Gemini's OpenAI compatibility endpoint, OpenRouter, or a local Ollama).
Only the standard library is used, so enabling the advisor adds no runtime
dependency and no provider SDK.

The client sends exactly the two supplied messages. It never logs the API key,
the prompt or the response body.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.core.config import Settings

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class LLMError(Exception):
    """A provider failure that must degrade to the deterministic explanation."""

    def __init__(self, message: str, *, code: str = "provider_error", retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    model: str
    attempts: int
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)


Opener = Callable[[Request, float], Any]


class OpenAICompatibleClient:
    """A bounded JSON-mode client for one configured provider."""

    def __init__(
        self,
        settings: Settings,
        *,
        opener: Opener | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._settings = settings
        self._opener = opener or _default_opener
        self._sleeper = sleeper or time.sleep

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Return the assistant message content, retrying transient failures."""
        endpoint = _chat_endpoint(self._settings.llm_base_url)
        _require_safe_transport(endpoint)

        api_key = self._settings.llm_api_key.get_secret_value().strip()
        if not api_key:
            raise LLMError(
                "No LLM API key is configured.", code="missing_api_key", retryable=False
            )

        payload = self._payload(system_prompt, user_prompt)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "CloudPilot-AI/0.1 (+local-first)",
        }

        attempts_allowed = self._settings.llm_max_retries + 1
        last: LLMError | None = None
        for attempt in range(1, attempts_allowed + 1):
            request = Request(endpoint, data=body, headers=headers, method="POST")
            started = time.perf_counter()
            try:
                raw = self._read(request)
            except LLMError as exc:
                last = exc
                if not exc.retryable or attempt >= attempts_allowed:
                    raise
            except HTTPError as exc:
                status = exc.code
                exc.close()
                last = LLMError(
                    f"Provider returned HTTP {status}.",
                    code="provider_error",
                    retryable=status in RETRYABLE_STATUS,
                )
                if not last.retryable or attempt >= attempts_allowed:
                    raise last from exc
            except URLError as exc:
                code = "timeout" if isinstance(exc.reason, TimeoutError) else "provider_error"
                last = LLMError("The LLM provider could not be reached.", code=code, retryable=True)
                if attempt >= attempts_allowed:
                    raise last from exc
            except TimeoutError as exc:
                last = LLMError("The LLM provider timed out.", code="timeout", retryable=True)
                if attempt >= attempts_allowed:
                    raise last from exc
            else:
                latency_ms = int((time.perf_counter() - started) * 1000)
                return _parse_response(
                    raw,
                    model=self._settings.llm_model,
                    attempts=attempt,
                    latency_ms=latency_ms,
                    maximum=self._settings.llm_max_response_bytes,
                )

            self._sleeper(min(0.5 * (2 ** (attempt - 1)), 4.0))

        # The loop either returns or raises; this is defensive only.
        raise last or LLMError("The LLM provider failed.", code="provider_error")

    def _payload(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": float(self._settings.llm_temperature),
            "max_tokens": self._settings.llm_max_output_tokens,
            "stream": False,
        }
        if self._settings.llm_json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _read(self, request: Request) -> bytes:
        maximum = self._settings.llm_max_response_bytes
        with self._opener(request, self._settings.llm_timeout_seconds) as response:
            raw: bytes = response.read(maximum + 1)
        if len(raw) > maximum:
            raise LLMError(
                "The LLM response exceeded the configured size limit.",
                code="response_too_large",
                retryable=False,
            )
        return raw


def create_client(
    settings: Settings,
    *,
    opener: Opener | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(settings, opener=opener, sleeper=sleeper)


def _default_opener(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)  # noqa: S310 - scheme is validated first


def _chat_endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        raise LLMError("The LLM base URL is empty.", code="insecure_transport", retryable=False)
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _require_safe_transport(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and (parsed.hostname or "").lower() in LOCAL_HOSTS:
        return
    raise LLMError(
        "The LLM base URL must use HTTPS, or HTTP on localhost for a local model.",
        code="insecure_transport",
        retryable=False,
    )


def _parse_response(
    raw: bytes,
    *,
    model: str,
    attempts: int,
    latency_ms: int,
    maximum: int,
) -> LLMResponse:
    if len(raw) > maximum:
        raise LLMError(
            "The LLM response exceeded the configured size limit.",
            code="response_too_large",
            retryable=False,
        )
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LLMError(
            "The LLM provider returned a non-JSON response.",
            code="invalid_response",
            retryable=False,
        ) from exc
    if not isinstance(body, dict):
        raise LLMError("The LLM provider returned an unexpected payload.", code="invalid_response")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("The LLM response contained no choices.", code="invalid_response")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMError("The LLM response contained no message.", code="invalid_response")
    message = first.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise LLMError("The LLM response contained no text.", code="invalid_response")
    content = message["content"].strip()
    if not content:
        raise LLMError("The LLM response was empty.", code="invalid_response")
    usage: dict[str, Any] = body["usage"] if isinstance(body.get("usage"), dict) else {}
    model_value = body.get("model")
    returned_model: str = model_value if isinstance(model_value, str) else model
    return LLMResponse(
        content=content,
        model=returned_model,
        attempts=attempts,
        latency_ms=latency_ms,
        usage=usage,
    )
