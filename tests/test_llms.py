"""
Tests for the OpenRouter interface. HTTP requests are intercepted, so LiteLLM builds real requests
and parses real responses, but nothing leaves the machine.
"""

import json
import httpx
import pytest
from pydantic import ValidationError
from interfaces.llms import LLM, OPENROUTER_MODELS
from models.moves import Move

OTHERS = ["Blake", "Charlie", "Drew"]

VALID_REPLY = {
    "secret_strategy": "Befriend Blake, then squeeze Charlie",
    "give_coin_to": "Blake",
    "take_coin_from": "Charlie",
    "private_messages": {name: f"Hi {name}" for name in OTHERS},
}


class FakeOpenRouter:
    """
    Records each HTTP request and replies with a chat completion containing self.content
    """

    def __init__(self):
        self.requests = []
        self.content = json.dumps(VALID_REPLY)

    def send(self, request, **kwargs):
        """
        Patched in as httpx.Client.send; as a bound method, it isn't passed the client
        """
        self.requests.append(request)
        completion = {
            "id": "gen-test",
            "object": "chat.completion",
            "created": 0,
            "model": json.loads(request.content)["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": self.content},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        return httpx.Response(200, json=completion, request=request)

    def body(self) -> dict:
        return json.loads(self.requests[-1].content)


@pytest.fixture
def openrouter(monkeypatch) -> FakeOpenRouter:
    fake = FakeOpenRouter()
    monkeypatch.setattr(httpx.Client, "send", fake.send)
    return fake


def test_request_goes_to_openrouter_with_a_strict_schema(openrouter):
    LLM("claude-haiku-4-5").send("the rules", "your move", Move.response_format(OTHERS))
    request = openrouter.requests[-1]
    assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = openrouter.body()
    assert body["model"] == "anthropic/claude-haiku-4.5"
    assert body["messages"] == [
        {"role": "system", "content": "the rules"},
        {"role": "user", "content": "your move"},
    ]
    assert body["provider"] == {"require_parameters": True}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["give_coin_to"]["enum"] == OTHERS
    assert "temperature" not in body


LOWER_REASONING = {
    "deepseek/deepseek-v4.1-flash-1017": "none",
    "xiaomi/mimo-v2.6-flash": "none",
}


@pytest.mark.parametrize("model_name", LLM.all_model_names())
def test_every_model_is_routed_to_its_openrouter_id_with_its_reasoning_effort(
    openrouter, model_name
):
    LLM(model_name).send("the rules", "your move", Move.response_format(OTHERS))
    body = openrouter.body()
    assert body["model"] == OPENROUTER_MODELS[model_name]
    assert body["reasoning"] == {"effort": LOWER_REASONING.get(model_name, "low")}
    assert "reasoning_effort" not in body


def test_reply_is_parsed_into_the_schema(openrouter):
    response = LLM("gpt-5-nano").send(
        "the rules", "your move", Move.response_format(OTHERS)
    )
    move = Move.from_response(response)
    assert move.give == "Blake"
    assert move.take == "Charlie"
    assert move.messages == {name: f"Hi {name}" for name in OTHERS}


@pytest.mark.parametrize(
    "change",
    [
        {"give_coin_to": "Alex"},
        {"private_messages": {"Blake": "Hi Blake"}},
    ],
)
def test_reply_that_breaks_the_schema_is_rejected(openrouter, change):
    openrouter.content = json.dumps({**VALID_REPLY, **change})
    with pytest.raises(ValidationError):
        LLM("gpt-5-nano").send("the rules", "your move", Move.response_format(OTHERS))


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        LLM("grok-4-fast")
