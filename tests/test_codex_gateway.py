"""Tests for the Codex CLI gateway shim."""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from autodialectics.routing import codex_gateway


def test_extract_codex_response_parses_jsonl_output() -> None:
    content, usage = codex_gateway._extract_codex_response(
        "\n".join(
            [
                '{"type":"thread.started","thread_id":"abc"}',
                '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"hello"}}',
                '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":5}}',
            ]
        )
    )

    assert content == "hello"
    assert usage == {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "total_tokens": 17,
    }


def test_chat_completions_adapts_codex_result_to_openai_shape(monkeypatch) -> None:
    async def fake_call(system_prompt: str, user_prompt: str, model: str) -> dict[str, object]:
        assert system_prompt == "System guidance"
        assert user_prompt == "User request"
        assert model == "gpt-5.4-mini"
        return {
            "result": "gateway ok",
            "usage": {
                "prompt_tokens": 17,
                "completion_tokens": 5,
                "total_tokens": 22,
            },
        }

    monkeypatch.setattr(codex_gateway, "_call_codex", fake_call)
    client = TestClient(codex_gateway.app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-5.4-mini",
            "messages": [
                {"role": "system", "content": "System guidance"},
                {"role": "user", "content": "User request"},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "gpt-5.4-mini"
    assert payload["choices"][0]["message"]["content"] == "gateway ok"
    assert payload["usage"] == {
        "prompt_tokens": 17,
        "completion_tokens": 5,
        "total_tokens": 22,
    }


def test_list_models_uses_default_model(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_GATEWAY_MODEL", "gpt-5.4")
    client = TestClient(codex_gateway.app)

    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"][0]["id"] == "gpt-5.4"


def test_resolve_model_maps_default_to_gateway_default(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_GATEWAY_MODEL", "gpt-5.4")

    assert codex_gateway._resolve_model("default") == "gpt-5.4"
    assert codex_gateway._resolve_model("") == "gpt-5.4"
    assert codex_gateway._resolve_model("gpt-5.4-mini") == "gpt-5.4-mini"


def test_main_accepts_runtime_flags(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app, host: str, port: int, log_level: str) -> None:
        captured["host"] = host
        captured["port"] = port
        captured["log_level"] = log_level

    monkeypatch.delenv("CODEX_GATEWAY_HOST", raising=False)
    monkeypatch.delenv("CODEX_GATEWAY_PORT", raising=False)
    monkeypatch.delenv("CODEX_GATEWAY_MODEL", raising=False)
    monkeypatch.delenv("CODEX_GATEWAY_KEY", raising=False)
    monkeypatch.setattr(codex_gateway.uvicorn, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "codex-gateway",
        "--host", "127.0.0.3",
        "--port", "8775",
        "--model", "gpt-5.4",
        "--api-key", "secret",
    ])

    codex_gateway.main()

    assert captured == {"host": "127.0.0.3", "port": 8775, "log_level": "info"}
    assert codex_gateway._get_default_model() == "gpt-5.4"
    assert codex_gateway._get_api_key() == "secret"
