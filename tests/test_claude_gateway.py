"""Tests for the Claude CLI gateway shim."""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from autodialectics.routing import claude_gateway


def test_list_models_returns_openai_compatible_shape() -> None:
    client = TestClient(claude_gateway.app)

    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    assert {model["id"] for model in payload["data"]} == {
        "claude-sonnet",
        "claude-opus",
        "claude-haiku",
    }


def test_chat_completions_adapts_claude_result_to_openai_shape(monkeypatch) -> None:
    async def fake_call(system_prompt: str, user_prompt: str, model: str) -> dict[str, object]:
        assert system_prompt == "System guidance"
        assert user_prompt == "User request"
        assert model == "sonnet"
        return {
            "result": "gateway ok",
            "usage": {
                "input_tokens": 12,
                "output_tokens": 5,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 2,
            },
            "stop_reason": "end_turn",
            "total_cost_usd": 0.01,
        }

    monkeypatch.setattr(claude_gateway, "_call_claude", fake_call)
    client = TestClient(claude_gateway.app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "default",
            "messages": [
                {"role": "system", "content": "System guidance"},
                {"role": "user", "content": "User request"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "claude-sonnet"
    assert payload["choices"][0]["message"]["content"] == "gateway ok"
    assert payload["usage"] == {
        "prompt_tokens": 17,
        "completion_tokens": 5,
        "total_tokens": 22,
    }
    assert payload["_claude_meta"]["stop_reason"] == "end_turn"


def test_main_accepts_runtime_flags(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app, host: str, port: int, log_level: str) -> None:
        captured["host"] = host
        captured["port"] = port
        captured["log_level"] = log_level

    monkeypatch.delenv("CLAUDE_GATEWAY_HOST", raising=False)
    monkeypatch.delenv("CLAUDE_GATEWAY_PORT", raising=False)
    monkeypatch.delenv("CLAUDE_GATEWAY_MODEL", raising=False)
    monkeypatch.delenv("CLAUDE_GATEWAY_KEY", raising=False)
    monkeypatch.setattr(claude_gateway.uvicorn, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "claude-gateway",
        "--host", "127.0.0.4",
        "--port", "8776",
        "--model", "opus",
        "--api-key", "secret",
    ])

    claude_gateway.main()

    assert captured == {"host": "127.0.0.4", "port": 8776, "log_level": "info"}
    assert claude_gateway._get_default_model() == "opus"
    assert claude_gateway._get_api_key() == "secret"
