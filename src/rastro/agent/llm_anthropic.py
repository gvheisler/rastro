import json
from collections.abc import Sequence
from typing import Any

import anthropic

from rastro.agent.llm import Completion, LLMError, Message, ToolCall

MAX_TOKENS = 16000
REPLAY_LIMIT = 64
REFUSED_TEXT = "O modelo de linguagem recusou este pedido."


class AnthropicClient:
    """Chat client for the Claude API (Messages API), behind the same interface as the others.

    The agent keeps its conversation in the OpenAI chat format; this client translates it on
    each call. Claude's own content blocks (thinking included) are kept and sent back as they
    came, because the API expects them unchanged during a tool-calling turn.
    """

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        effort: str | None = None,
        timeout: float = 300,
        max_retries: int = 2,
        http_client: Any = None,
    ) -> None:
        self.model = model
        self._effort = effort
        self._options: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": timeout,
            "max_retries": max_retries,
            "http_client": http_client,
        }
        self._client: anthropic.Anthropic | None = None
        self._replay: dict[tuple[str, ...], Any] = {}

    def complete(self, messages: Sequence[Message], tools: Sequence[dict[str, Any]]) -> Completion:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "messages": self._messages(messages),
        }
        if system:
            request["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        if tools:
            request["tools"] = [_tool(spec) for spec in tools]
        if self._effort:
            request["output_config"] = {"effort": self._effort}

        try:
            if self._client is None:
                self._client = anthropic.Anthropic(**self._options)
            response = self._client.messages.create(**request)
        except anthropic.APIStatusError as error:
            raise LLMError(f"Claude API returned {error.status_code}: {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise LLMError(f"Could not reach the Claude API: {error}") from error
        except (anthropic.AnthropicError, TypeError) as error:
            # No credentials: the SDK raises TypeError when it cannot build the auth headers.
            raise LLMError(f"Claude API: {error}") from error

        usage = response.usage
        input_tokens = (
            usage.input_tokens
            + (usage.cache_read_input_tokens or 0)
            + (usage.cache_creation_input_tokens or 0)
        )
        if response.stop_reason == "refusal":
            refusal = ToolCall("refusal", "refuse", {"reason": REFUSED_TEXT})
            return Completion("", (refusal,), input_tokens, usage.output_tokens)

        text = "".join(block.text for block in response.content if block.type == "text")
        calls = tuple(
            ToolCall(block.id, block.name, dict(block.input))
            for block in response.content
            if block.type == "tool_use"
        )
        self._remember(text, calls, response.content)
        return Completion(text, calls, input_tokens, usage.output_tokens)

    def _remember(self, text: str, calls: Sequence[ToolCall], content: Any) -> None:
        if not content:
            return
        self._replay[_key(text, [call.id for call in calls])] = content
        while len(self._replay) > REPLAY_LIMIT:
            del self._replay[next(iter(self._replay))]

    def _messages(self, messages: Sequence[Message]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role, content = message["role"], message.get("content") or ""
            if role == "user":
                converted.append({"role": "user", "content": content})
            elif role == "assistant":
                blocks = self._assistant_blocks(content, message.get("tool_calls") or [])
                if blocks:
                    converted.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                result = {
                    "type": "tool_result",
                    "tool_use_id": message["tool_call_id"],
                    "content": content,
                }
                previous = converted[-1] if converted else None
                if (
                    previous
                    and previous["role"] == "user"
                    and isinstance(previous["content"], list)
                ):
                    previous["content"].append(result)
                else:
                    converted.append({"role": "user", "content": [result]})
        return converted

    def _assistant_blocks(self, text: str, tool_calls: Sequence[dict[str, Any]]) -> Any:
        original = self._replay.get(_key(text, [call["id"] for call in tool_calls]))
        if original is not None:
            return original
        blocks: list[dict[str, Any]] = [{"type": "text", "text": text}] if text.strip() else []
        for call in tool_calls:
            function = call["function"]
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):
                arguments = json.loads(arguments or "{}")
            blocks.append(
                {"type": "tool_use", "id": call["id"], "name": function["name"], "input": arguments}
            )
        return blocks


def _key(text: str, tool_call_ids: Sequence[str]) -> tuple[str, ...]:
    return ("calls", *tool_call_ids) if tool_call_ids else ("text", text)


def _tool(spec: dict[str, Any]) -> dict[str, Any]:
    function = spec["function"]
    return {
        "name": function["name"],
        "description": function.get("description", ""),
        "input_schema": function["parameters"],
    }
