import json

import httpx2
import pytest
from anthropic import DefaultHttpxClient

from rastro.agent.llm import LLMError, ToolCall, build_llm
from rastro.agent.llm_anthropic import AnthropicClient
from rastro.config import Settings

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "Executa uma consulta.",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    }
]
MESSAGES = [
    {"role": "system", "content": "Regras."},
    {"role": "user", "content": "Quanto foi pago?"},
]
THINKING = {"type": "thinking", "thinking": "", "signature": "sig-1"}
TOOL_USE = {"type": "tool_use", "id": "toolu_1", "name": "run_sql", "input": {"sql": "select 1"}}


def reply(content: list[dict], stop_reason: str = "end_turn", **extra) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 11, "output_tokens": 7},
            **extra,
        },
    )


def client_for(handler, **kwargs) -> AnthropicClient:
    http = DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    kwargs.setdefault("api_key", "test-key")
    return AnthropicClient("claude-test", http_client=http, max_retries=0, **kwargs)


def recorder(responses: list[httpx2.Response]):
    seen: list[dict] = []
    queue = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append({"body": json.loads(request.content), "headers": request.headers})
        return queue.pop(0)

    return seen, handler


def test_request_uses_the_messages_api_shape():
    seen, handler = recorder([reply([{"type": "text", "text": "ola"}])])
    client_for(handler).complete(MESSAGES, TOOLS)
    body = seen[0]["body"]
    assert body["model"] == "claude-test"
    assert body["system"] == [
        {"type": "text", "text": "Regras.", "cache_control": {"type": "ephemeral"}}
    ]
    assert body["messages"] == [{"role": "user", "content": "Quanto foi pago?"}]
    assert body["tools"] == [
        {
            "name": "run_sql",
            "description": "Executa uma consulta.",
            "input_schema": TOOLS[0]["function"]["parameters"],
        }
    ]
    assert body["max_tokens"] > 0
    assert "temperature" not in body
    assert "output_config" not in body
    assert seen[0]["headers"]["authorization"] == "Bearer test-key"


def test_tools_are_omitted_when_there_are_none():
    seen, handler = recorder([reply([{"type": "text", "text": "ola"}])])
    client_for(handler).complete(MESSAGES, [])
    assert "tools" not in seen[0]["body"]


def test_effort_is_sent_when_configured():
    seen, handler = recorder([reply([{"type": "text", "text": "ola"}])])
    client_for(handler, effort="low").complete(MESSAGES, TOOLS)
    assert seen[0]["body"]["output_config"] == {"effort": "low"}


def test_text_tool_calls_and_usage_are_parsed():
    usage = {
        "input_tokens": 5,
        "output_tokens": 7,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 20,
    }
    _, handler = recorder(
        [reply([{"type": "text", "text": "Vou consultar."}, TOOL_USE], "tool_use", usage=usage)]
    )
    completion = client_for(handler).complete(MESSAGES, TOOLS)
    assert completion.text == "Vou consultar."
    assert completion.tool_calls == (ToolCall("toolu_1", "run_sql", {"sql": "select 1"}),)
    assert (completion.input_tokens, completion.output_tokens) == (125, 7)


def test_tool_results_go_back_in_one_user_message_after_the_original_blocks():
    seen, handler = recorder(
        [
            reply([THINKING, TOOL_USE, {**TOOL_USE, "id": "toolu_2"}], "tool_use"),
            reply([{"type": "text", "text": "Foi 1."}]),
        ]
    )
    client = client_for(handler)
    first = client.complete(MESSAGES, TOOLS)
    history = [
        *MESSAGES,
        {
            "role": "assistant",
            "content": first.text,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in first.tool_calls
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "content": "1 row"},
        {"role": "tool", "tool_call_id": "toolu_2", "content": "2 rows"},
    ]
    client.complete(history, TOOLS)
    sent = seen[1]["body"]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[1]["content"][0] == THINKING
    assert [block["id"] for block in sent[1]["content"][1:]] == ["toolu_1", "toolu_2"]
    assert sent[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "1 row"},
        {"type": "tool_result", "tool_use_id": "toolu_2", "content": "2 rows"},
    ]


def test_assistant_turns_from_elsewhere_are_rebuilt_from_the_chat_format():
    seen, handler = recorder([reply([{"type": "text", "text": "ok"}])])
    history = [
        *MESSAGES,
        {"role": "assistant", "content": "Foi 10.\n[SQL usado: select 10]"},
        {"role": "user", "content": "E em 2024?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "run_sql", "arguments": '{"sql": "select 2"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "1 row"},
    ]
    client_for(handler).complete(history, TOOLS)
    sent = seen[0]["body"]["messages"]
    assert sent[1] == {
        "role": "assistant",
        "content": [{"type": "text", "text": "Foi 10.\n[SQL usado: select 10]"}],
    }
    assert sent[3]["content"] == [
        {"type": "tool_use", "id": "c1", "name": "run_sql", "input": {"sql": "select 2"}}
    ]


def test_empty_assistant_turns_are_left_out():
    seen, handler = recorder([reply([{"type": "text", "text": "ok"}])])
    history = [
        *MESSAGES,
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "Use run_sql."},
    ]
    client_for(handler).complete(history, TOOLS)
    assert [m["role"] for m in seen[0]["body"]["messages"]] == ["user", "user"]


def test_a_model_refusal_becomes_a_refuse_tool_call():
    _, handler = recorder(
        [reply([], "refusal", stop_details={"type": "refusal", "category": "cyber"})]
    )
    completion = client_for(handler).complete(MESSAGES, TOOLS)
    assert [call.name for call in completion.tool_calls] == ["refuse"]
    assert completion.tool_calls[0].arguments["reason"]


def test_api_errors_become_llm_errors_with_the_status_and_message():
    error = {"type": "error", "error": {"type": "not_found_error", "message": "model: nope"}}
    client = client_for(lambda r: httpx2.Response(404, json=error))
    with pytest.raises(LLMError, match="404.*model: nope"):
        client.complete(MESSAGES, TOOLS)


def test_connection_failures_become_llm_errors():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    with pytest.raises(LLMError, match="Claude API"):
        client_for(handler).complete(MESSAGES, TOOLS)


def test_a_missing_key_is_reported_as_an_llm_error(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent")
    monkeypatch.setenv("HOME", "/nonexistent")
    client = AnthropicClient("claude-test", max_retries=0)
    with pytest.raises(LLMError):
        client.complete(MESSAGES, TOOLS)


def settings(monkeypatch, **env) -> Settings:
    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("READONLY_PASSWORD", "y")
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "ANTHROPIC_API_KEY", "LLM_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def test_build_llm_returns_the_claude_client_for_the_anthropic_provider(monkeypatch):
    client = build_llm(settings(monkeypatch, LLM_PROVIDER="anthropic"))
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-opus-5-5"


def test_build_llm_passes_the_model_chosen_for_claude(monkeypatch):
    client = build_llm(
        settings(monkeypatch, LLM_PROVIDER="anthropic", LLM_MODEL="claude-haiku-5-5")
    )
    assert client.model == "claude-haiku-5-5"
