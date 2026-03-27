"""Tests for the generic auto-detecting CLI gateway."""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from autodialectics.routing import cli_gateway


def test_detect_provider_prefers_current_codex_environment(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-123")
    monkeypatch.setattr(
        cli_gateway,
        "_available_provider_commands",
        lambda: {"codex": True, "claude": True, "hermes": True},
    )

    assert cli_gateway._detect_provider() == "codex"


def test_health_reports_auto_detected_provider(monkeypatch) -> None:
    monkeypatch.setenv("CLI_GATEWAY_PROVIDER", "auto")
    monkeypatch.setattr(cli_gateway, "_detect_provider", lambda: "claude")
    client = TestClient(cli_gateway.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["provider"] == "claude"


def test_chat_completions_routes_to_resolved_provider(monkeypatch) -> None:
    async def fake_call(provider: str, system_prompt: str, user_prompt: str, model: str):
        assert provider == "hermes"
        assert system_prompt == "System guidance"
        assert user_prompt == "User request"
        assert model == "auto"
        return {
            "result": "gateway ok",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    monkeypatch.setenv("CLI_GATEWAY_PROVIDER", "hermes")
    monkeypatch.setattr(cli_gateway, "_call_provider", fake_call)
    client = TestClient(cli_gateway.app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {"role": "system", "content": "System guidance"},
                {"role": "user", "content": "User request"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "gateway ok"
    assert payload["_cli_meta"]["provider"] == "hermes"


def test_chat_completions_maps_default_model_for_codex(monkeypatch) -> None:
    async def fake_call(provider: str, system_prompt: str, user_prompt: str, model: str):
        assert provider == "codex"
        assert model == "gpt-5.4-mini"
        return {
            "result": "gateway ok",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    monkeypatch.setenv("CLI_GATEWAY_PROVIDER", "codex")
    monkeypatch.delenv("CLI_GATEWAY_MODEL", raising=False)
    monkeypatch.delenv("CODEX_GATEWAY_MODEL", raising=False)
    monkeypatch.setattr(cli_gateway, "_call_provider", fake_call)
    client = TestClient(cli_gateway.app)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "default",
            "messages": [
                {"role": "user", "content": "User request"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["model"] == "gpt-5.4-mini"


def test_main_accepts_runtime_flags(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app, host: str, port: int, log_level: str) -> None:
        captured["host"] = host
        captured["port"] = port
        captured["log_level"] = log_level

    monkeypatch.delenv("CLI_GATEWAY_HOST", raising=False)
    monkeypatch.delenv("CLI_GATEWAY_PORT", raising=False)
    monkeypatch.delenv("CLI_GATEWAY_PROVIDER", raising=False)
    monkeypatch.delenv("CLI_GATEWAY_MODEL", raising=False)
    monkeypatch.delenv("CLI_GATEWAY_KEY", raising=False)
    monkeypatch.setattr(cli_gateway, "_resolve_provider", lambda: "codex")
    monkeypatch.setattr(cli_gateway.uvicorn, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "cli-gateway",
        "--host", "127.0.0.2",
        "--port", "8774",
        "--provider", "codex",
        "--model", "gpt-5.4",
        "--api-key", "secret",
    ])

    cli_gateway.main()

    assert captured == {"host": "127.0.0.2", "port": 8774, "log_level": "info"}
    assert cli_gateway._preferred_provider() == "codex"
    assert cli_gateway._get_api_key() == "secret"
