from __future__ import annotations

import asyncio
import json

import pytest

from llm_json import call_anthropic_text, extract_json_object


def test_extract_json_object_accepts_plain_json():
    assert extract_json_object('{"session_summary": "ok", "updated_profile": "new"}') == {
        "session_summary": "ok",
        "updated_profile": "new",
    }


def test_extract_json_object_accepts_fenced_json():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_object_falls_back_to_first_object_in_prose():
    assert extract_json_object('Here it is: {"a": 1, "b": 2}. Done.') == {"a": 1, "b": 2}


def test_extract_json_object_raises_when_no_json_object_exists():
    with pytest.raises(json.JSONDecodeError):
        extract_json_object("no json here")


class FakeBlock:
    def __init__(self, text):
        self.text = text


class FakeMessages:
    def __init__(self, blocks, captured):
        self._blocks = blocks
        self._captured = captured

    def create(self, **kwargs):
        self._captured.update(kwargs)

        class _Msg:
            content = self._blocks

        return _Msg()


def test_call_anthropic_text_passes_args_and_concatenates_text_blocks(monkeypatch):
    captured = {}

    class FakeAnthropic:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.messages = FakeMessages([FakeBlock("Hello "), FakeBlock("world")], captured)

    monkeypatch.setattr("llm_json.anthropic.Anthropic", FakeAnthropic)

    result = asyncio.run(
        call_anthropic_text(
            api_key="key-123",
            model="model-x",
            system="be terse",
            prompt="say hi",
            max_tokens=42,
        )
    )

    assert result == "Hello world"
    assert captured["api_key"] == "key-123"
    assert captured["model"] == "model-x"
    assert captured["system"] == "be terse"
    assert captured["max_tokens"] == 42
    assert captured["messages"] == [{"role": "user", "content": "say hi"}]


def test_call_anthropic_text_defaults_max_tokens(monkeypatch):
    captured = {}

    class FakeAnthropic:
        def __init__(self, api_key):
            self.messages = FakeMessages([FakeBlock("ok")], captured)

    monkeypatch.setattr("llm_json.anthropic.Anthropic", FakeAnthropic)

    asyncio.run(call_anthropic_text(api_key=None, model="m", system="s", prompt="p"))

    assert captured["max_tokens"] == 1500
