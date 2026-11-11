import json

import httpx
import pytest

from rastro.agent.llm import LLMError, OpenAICompatibleClient, ToolCall

TOOLS = [{"type": "function", "function": {"name": "run_sql", "parameters": {"type": "object"}}}]
MESSAGES = [{"role": "user", "content": "oi"}]


def client_for(handler, **kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        "http://llm.test/v1", "modelo", transport=httpx.MockTransport(handler), **kwargs
    )


def reply(message: dict, usage: dict | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message}],
            "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7},
        },
    )


def test_request_carries_model_messages_tools_and_deterministic_sampling():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return reply({"role": "assistant", "content": "ola"})

    client_for(handler).complete(MESSAGES, TOOLS)
    assert seen["url"] == "http://llm.test/v1/chat/completions"
    assert seen["body"]["model"] == "modelo"
    assert seen["body"]["messages"] == MESSAGES
    assert seen["body"]["tools"] == TOOLS
    assert seen["body"]["temperature"] == 0


def test_tools_are_omitted_when_there_are_none():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return reply({"role": "assistant", "content": "ola"})

    client_for(handler).complete(MESSAGES, [])
    assert "tools" not in seen["body"]


def test_extra_body_and_api_key_are_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return reply({"role": "assistant", "content": "ola"})

    client_for(handler, extra_body={"reasoning_effort": "none"}, api_key="k").complete(
        MESSAGES, TOOLS
    )
    assert seen["body"]["reasoning_effort"] == "none"
    assert seen["auth"] == "Bearer k"


def test_text_reply_and_usage_are_parsed():
    completion = client_for(lambda r: reply({"role": "assistant", "content": "Resposta"})).complete(
        MESSAGES, TOOLS
    )
    assert completion.text == "Resposta"
    assert completion.tool_calls == ()
    assert (completion.input_tokens, completion.output_tokens) == (11, 7)


def test_tool_calls_are_parsed_with_json_arguments():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "run_sql", "arguments": '{"sql": "select 1"}'},
            }
        ],
    }
    completion = client_for(lambda r: reply(message)).complete(MESSAGES, TOOLS)
    assert completion.text == ""
    assert completion.tool_calls == (ToolCall("c1", "run_sql", {"sql": "select 1"}),)


def test_arguments_that_are_already_objects_are_accepted():
    message = {
        "role": "assistant",
        "tool_calls": [{"id": "c1", "function": {"name": "run_sql", "arguments": {"sql": "x"}}}],
    }
    call = client_for(lambda r: reply(message)).complete(MESSAGES, TOOLS).tool_calls[0]
    assert call.arguments == {"sql": "x"}


def test_invalid_json_arguments_are_reported_instead_of_raised():
    message = {
        "role": "assistant",
        "tool_calls": [{"id": "c1", "function": {"name": "run_sql", "arguments": "{sql: oops"}}],
    }
    call = client_for(lambda r: reply(message)).complete(MESSAGES, TOOLS).tool_calls[0]
    assert call.arguments == {}
    assert call.error and "JSON" in call.error


def test_missing_tool_call_id_gets_a_generated_one():
    message = {
        "role": "assistant",
        "tool_calls": [{"function": {"name": "run_sql", "arguments": "{}"}}],
    }
    call = client_for(lambda r: reply(message)).complete(MESSAGES, TOOLS).tool_calls[0]
    assert call.id


def test_http_errors_become_llm_errors_with_the_server_message():
    client = client_for(lambda r: httpx.Response(500, text="model not found"))
    with pytest.raises(LLMError, match="500.*model not found"):
        client.complete(MESSAGES, TOOLS)


def test_unreachable_server_becomes_an_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMError, match="http://llm.test/v1"):
        client_for(handler).complete(MESSAGES, TOOLS)


def test_temperature_can_be_left_out():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return reply({"role": "assistant", "content": "ola"})

    client_for(handler, temperature=None).complete(MESSAGES, TOOLS)
    assert "temperature" not in seen["body"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>gateway</html>"),
        httpx.Response(200, json={"error": "overloaded"}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json=["nope"]),
    ],
)
def test_unexpected_reply_bodies_become_llm_errors(response):
    with pytest.raises(LLMError, match="unexpected reply"):
        client_for(lambda r: response).complete(MESSAGES, TOOLS)


def test_build_llm_uses_the_settings(monkeypatch):
    from rastro.agent.llm import build_llm
    from rastro.config import Settings

    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("READONLY_PASSWORD", "y")
    monkeypatch.setenv("LLM_MODEL", "outro-modelo")
    client = build_llm(Settings(_env_file=None))
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model == "outro-modelo"
