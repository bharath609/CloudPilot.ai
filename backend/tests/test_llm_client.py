"""OpenAI-compatible client: transport safety, retries, payload and parsing."""

from __future__ import annotations

import io
import json
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from app.core.config import Settings
from app.llm.client import LLMError, OpenAICompatibleClient, _chat_endpoint, _parse_response


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "llm_enabled": True,
        "llm_api_key": "test-key-not-real",
        "llm_base_url": "https://api.example.test/openai/v1",
        "llm_model": "test-model",
        "llm_timeout_seconds": 5.0,
        "llm_max_retries": 2,
        "llm_max_response_bytes": 20_000,
        "database_url": "sqlite://",
    }
    values.update(overrides)
    return Settings(**values)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def _completion(content: str, *, model: str = "test-model") -> bytes:
    return json.dumps(
        {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 6},
        }
    ).encode()


def test_https_endpoint_is_used_and_payload_has_no_secret_in_body() -> None:
    captured: dict[str, Any] = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(_completion('{"ok": true}'))

    client = OpenAICompatibleClient(_settings(), opener=opener, sleeper=lambda _s: None)
    response = client.complete_json(system_prompt="system", user_prompt="user")

    assert captured["url"] == "https://api.example.test/openai/v1/chat/completions"
    assert captured["timeout"] == 5.0
    payload = captured["body"]
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0.0
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert "test-key-not-real" not in json.dumps(payload)

    # The key is only in the Authorization header, never the body.
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["authorization"] == "Bearer test-key-not-real"
    assert response.content == '{"ok": true}'
    assert response.model == "test-model"
    assert response.attempts == 1
    assert response.usage["prompt_tokens"] == 5


def test_localhost_http_is_allowed() -> None:
    def opener(_request, _timeout):
        return FakeResponse(_completion("{}"))

    client = OpenAICompatibleClient(
        _settings(llm_base_url="http://127.0.0.1:11434/v1"),
        opener=opener,
        sleeper=lambda _s: None,
    )
    assert client.complete_json(system_prompt="s", user_prompt="u").attempts == 1


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.example.test/v1",
        "ftp://api.example.test/v1",
        "http://localhost.example.test/v1",
        "file:///tmp/model",
    ],
)
def test_insecure_transport_is_rejected_before_any_request(base_url: str) -> None:
    called = False

    def opener(_request, _timeout):  # pragma: no cover - must never run
        nonlocal called
        called = True
        return FakeResponse(_completion("{}"))

    client = OpenAICompatibleClient(_settings(llm_base_url=base_url), opener=opener)
    with pytest.raises(LLMError) as excinfo:
        client.complete_json(system_prompt="s", user_prompt="u")
    assert excinfo.value.code == "insecure_transport"
    assert called is False


def test_missing_api_key_is_rejected_before_any_request() -> None:
    called = False

    def opener(_request, _timeout):  # pragma: no cover - must never run
        nonlocal called
        called = True
        return FakeResponse(_completion("{}"))

    client = OpenAICompatibleClient(_settings(llm_api_key=""), opener=opener)
    with pytest.raises(LLMError) as excinfo:
        client.complete_json(system_prompt="s", user_prompt="u")
    assert excinfo.value.code == "missing_api_key"
    assert called is False


def test_retryable_status_is_retried_then_succeeds() -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def opener(request, _timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise HTTPError(request.full_url, 503, "unavailable", {}, io.BytesIO(b""))
        return FakeResponse(_completion("{}"))

    client = OpenAICompatibleClient(
        _settings(llm_max_retries=2), opener=opener, sleeper=sleeps.append
    )
    response = client.complete_json(system_prompt="s", user_prompt="u")
    assert len(attempts) == 3
    assert response.attempts == 3
    assert sleeps == [0.5, 1.0]


def test_non_retryable_status_is_not_retried() -> None:
    attempts: list[int] = []

    def opener(request, _timeout):
        attempts.append(1)
        raise HTTPError(request.full_url, 401, "unauthorized", {}, io.BytesIO(b""))

    client = OpenAICompatibleClient(
        _settings(llm_max_retries=3), opener=opener, sleeper=lambda _s: None
    )
    with pytest.raises(LLMError) as excinfo:
        client.complete_json(system_prompt="s", user_prompt="u")
    assert excinfo.value.code == "provider_error"
    assert len(attempts) == 1


def test_retries_are_bounded() -> None:
    attempts: list[int] = []

    def opener(request, _timeout):
        attempts.append(1)
        raise HTTPError(request.full_url, 500, "error", {}, io.BytesIO(b""))

    client = OpenAICompatibleClient(
        _settings(llm_max_retries=2), opener=opener, sleeper=lambda _s: None
    )
    with pytest.raises(LLMError):
        client.complete_json(system_prompt="s", user_prompt="u")
    assert len(attempts) == 3


def test_connection_failure_maps_to_provider_error() -> None:
    def opener(request, _timeout):
        raise URLError(ConnectionRefusedError("refused"))

    client = OpenAICompatibleClient(_settings(llm_max_retries=0), opener=opener)
    with pytest.raises(LLMError) as excinfo:
        client.complete_json(system_prompt="s", user_prompt="u")
    assert excinfo.value.code == "provider_error"


def test_oversized_response_is_rejected() -> None:
    def opener(_request, _timeout):
        return FakeResponse(b"x" * 30_000)

    client = OpenAICompatibleClient(_settings(llm_max_response_bytes=10_000), opener=opener)
    with pytest.raises(LLMError) as excinfo:
        client.complete_json(system_prompt="s", user_prompt="u")
    assert excinfo.value.code == "response_too_large"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"choices": []}',
        b'{"choices": [{}]}',
        b'{"choices": [{"message": {"content": "  "}}]}',
    ],
)
def test_malformed_provider_payloads_are_rejected(body: bytes) -> None:
    def opener(_request, _timeout):
        return FakeResponse(body)

    client = OpenAICompatibleClient(_settings(), opener=opener)
    with pytest.raises(LLMError) as excinfo:
        client.complete_json(system_prompt="s", user_prompt="u")
    assert excinfo.value.code == "invalid_response"


def test_chat_endpoint_is_not_doubled() -> None:
    assert (
        _chat_endpoint("https://api.example.test/v1/chat/completions")
        == "https://api.example.test/v1/chat/completions"
    )
    assert _chat_endpoint("https://api.example.test/v1/") == (
        "https://api.example.test/v1/chat/completions"
    )


def test_parse_response_rejects_oversized_body() -> None:
    with pytest.raises(LLMError) as excinfo:
        _parse_response(_completion("{}"), model="m", attempts=1, latency_ms=1, maximum=10)
    assert excinfo.value.code == "response_too_large"
