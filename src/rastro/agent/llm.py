import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

Message = dict[str, Any]


class LLMError(RuntimeError):
    """The model server could not produce a reply."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class Completion:
    text: str
    tool_calls: tuple[ToolCall, ...]
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    model: str

    def complete(self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]) -> Completion:
        """One chat turn. Messages and tools use the OpenAI chat format."""
        ...


class OpenAICompatibleClient:
    """Chat client for any server that speaks /v1/chat/completions (Ollama, vLLM, ...)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        extra_body: dict[str, Any] | None = None,
        timeout: float = 300,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._extra_body = extra_body or {}
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    def complete(self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": 0,
            **self._extra_body,
        }
        if tools:
            body["tools"] = list(tools)
        try:
            response = self._http.post(f"{self._base_url}/chat/completions", json=body)
        except httpx.HTTPError as error:
            raise LLMError(
                f"Could not reach the model server at {self._base_url}: {error}"
            ) from error
        if response.status_code >= 400:
            raise LLMError(f"Model server returned {response.status_code}: {response.text[:300]}")

        data = response.json()
        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return Completion(
            text=message.get("content") or "",
            tool_calls=tuple(_tool_call(raw) for raw in message.get("tool_calls") or []),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


def _tool_call(raw: dict[str, Any]) -> ToolCall:
    function = raw["function"]
    arguments, error = function.get("arguments") or {}, None
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("not an object")
        except ValueError:
            arguments, error = {}, "The arguments were not valid JSON."
    return ToolCall(
        raw.get("id") or f"call_{uuid.uuid4().hex[:8]}", function["name"], arguments, error
    )
