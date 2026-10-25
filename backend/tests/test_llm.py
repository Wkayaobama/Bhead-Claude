"""The LLM seam, exercised against a fake client — no network, no key."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app import llm
from app.config import settings


def text_response(text: str, stop_reason: str = "end_turn", stop_details=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=stop_details,
    )


class FakeMessages:
    def __init__(self, response=None, chunks=None):
        self.response = response
        self.chunks = chunks or []
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    @asynccontextmanager
    async def stream(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self.chunks
        response = self.response

        async def text_stream():
            for c in chunks:
                yield c

        async def get_final_message():
            return response

        yield SimpleNamespace(text_stream=text_stream(), get_final_message=get_final_message)


class FakeClient:
    def __init__(self, response=None, chunks=None):
        self.messages = FakeMessages(response, chunks)
        self.beta = SimpleNamespace(messages=FakeMessages(response, chunks))


@pytest.fixture
def fake_client(monkeypatch):
    holder: dict = {}

    def install(response=None, chunks=None, *, fallback: bool):
        client = FakeClient(response, chunks)
        monkeypatch.setattr(llm, "get_client", lambda: client)
        monkeypatch.setattr(settings, "ai_refusal_fallback", fallback)
        monkeypatch.setattr(settings, "ai_effort", "medium")
        holder["client"] = client
        return client

    return install


SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
        }
    },
    "required": ["jobs"],
}


async def test_extract_structured_parses_json_and_uses_output_config(fake_client):
    client = fake_client(text_response(json.dumps({"jobs": [{"title": "Dev"}]})), fallback=False)
    result = await llm.extract_structured(
        user_message="extract", schema=SCHEMA, system_prompt="You extract jobs."
    )
    assert result == {"jobs": [{"title": "Dev"}]}
    call = client.messages.calls[0]
    assert client.beta.messages.calls == []
    assert "fallbacks" not in call and "betas" not in call
    assert "tool_choice" not in call and "tools" not in call
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["properties"]["jobs"]["items"]["additionalProperties"] is False
    assert call["output_config"]["effort"] == "medium"
    assert call["model"] == settings.ai_model
    assert call["max_tokens"] == settings.extract_max_tokens


async def test_system_prompt_passes_through_without_any_identity_prelude(fake_client):
    client = fake_client(text_response("{}"), fallback=False)
    await llm.extract_structured(user_message="x", schema={"type": "object", "properties": {}},
                                 system_prompt="Be terse.")
    assert client.messages.calls[0]["system"] == "Be terse."
    assert "thinking" not in client.messages.calls[0]


async def test_refusal_fallback_routes_through_the_beta_surface(fake_client):
    client = fake_client(text_response("{}"), fallback=True)
    await llm.extract_structured(user_message="x", schema={"type": "object", "properties": {}})
    assert client.messages.calls == []
    call = client.beta.messages.calls[0]
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]


async def test_refusal_raises_instead_of_returning_partial_data(fake_client):
    fake_client(
        text_response("", "refusal", SimpleNamespace(category="cyber", explanation="nope")),
        fallback=False,
    )
    with pytest.raises(llm.LLMRefused) as excinfo:
        await llm.extract_structured(user_message="x", schema={"type": "object", "properties": {}})
    assert excinfo.value.category == "cyber"


async def test_truncated_output_raises(fake_client):
    fake_client(text_response('{"jobs": [', "max_tokens"), fallback=False)
    with pytest.raises(llm.LLMTruncated):
        await llm.extract_structured(
            user_message="x", schema={"type": "object", "properties": {}}, max_tokens=50
        )


async def test_stream_chat_yields_chunks_then_checks_the_final_message(fake_client):
    client = fake_client(text_response("Hello world"), chunks=["Hello", " world"], fallback=False)
    chunks = [c async for c in llm.stream_chat(user_message="hi", system_prompt="coach")]
    assert chunks == ["Hello", " world"]
    call = client.messages.calls[0]
    assert call["system"] == "coach"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["max_tokens"] == settings.chat_max_tokens


async def test_stream_chat_surfaces_a_refusal_after_the_stream(fake_client):
    fake_client(
        text_response("", "refusal", SimpleNamespace(category=None, explanation=None)),
        chunks=[],
        fallback=False,
    )
    with pytest.raises(llm.LLMRefused):
        async for _ in llm.stream_chat(user_message="hi"):
            pass


async def test_chat_once_returns_text_with_history(fake_client):
    client = fake_client(text_response("Sure."), fallback=False)
    reply = await llm.chat_once(
        user_message="again?", history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hey"}]
    )
    assert reply == "Sure."
    assert client.messages.calls[0]["messages"][-1] == {"role": "user", "content": "again?"}
    assert len(client.messages.calls[0]["messages"]) == 3


def test_strict_schema_recurses_and_does_not_mutate_the_input():
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "object", "properties": {"b": {"type": "string"}}},
            "list": {"type": "array", "items": {"type": "object", "properties": {}}},
            "either": {"anyOf": [{"type": "object", "properties": {}}, {"type": "string"}]},
        },
        "$defs": {"d": {"type": "object", "properties": {}, "additionalProperties": True}},
    }
    strict = llm._strict_schema(schema)
    assert strict["additionalProperties"] is False
    assert strict["properties"]["a"]["additionalProperties"] is False
    assert strict["properties"]["list"]["items"]["additionalProperties"] is False
    assert strict["properties"]["either"]["anyOf"][0]["additionalProperties"] is False
    assert strict["$defs"]["d"]["additionalProperties"] is True  # explicit values are kept
    assert "additionalProperties" not in schema


def test_get_client_fails_loudly_without_credentials(no_llm_credentials):
    assert llm.is_configured() is False
    with pytest.raises(llm.LLMNotConfigured, match="ANTHROPIC_API_KEY"):
        llm.get_client()
    assert llm.describe()["configured"] is False


def test_get_client_uses_the_configured_key(no_llm_credentials, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    client = llm.get_client()
    assert client.api_key == "sk-ant-test"
    assert llm.get_client() is client  # cached
    assert llm.describe()["configured"] is True
