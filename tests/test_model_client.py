"""Tests for ModelClient fallback semantics."""

from __future__ import annotations

import httpx

from autodialectics.routing.cliproxy import ModelClient


class RaisingHttpxClient:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, json: dict, headers: dict):
        request = httpx.Request("POST", url)
        response = httpx.Response(503, request=request, text="upstream unavailable")
        raise httpx.HTTPStatusError("service unavailable", request=request, response=response)


class CapturingHttpxClient:
    last_request_json = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, json: dict, headers: dict):
        CapturingHttpxClient.last_request_json = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "model": json["model"],
                "choices": [{"message": {"content": "ok"}}],
                "usage": {},
            },
        )


def test_model_client_reports_request_failures_without_claiming_offline(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", RaisingHttpxClient)
    client = ModelClient(base_url="http://127.0.0.1:8642")

    response = client.complete(
        role="executor",
        system_prompt="Return a result.",
        user_prompt="Do the task.",
    )

    assert response.content.startswith("[LLM REQUEST FAILED]")
    assert "HTTP 503" in response.content
    assert "No LLM endpoint configured" not in response.content


def test_model_client_still_reports_true_offline_mode() -> None:
    client = ModelClient(base_url="offline")

    response = client.complete(
        role="planner",
        system_prompt="Return a result.",
        user_prompt="Do the task.",
    )

    assert response.content.startswith("[OFFLINE MODE]")
    assert "No LLM endpoint configured" in response.content


def test_model_client_uses_configured_model_name(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "Client", CapturingHttpxClient)
    client = ModelClient(
        base_url="http://127.0.0.1:8642",
        model="gpt-5.4-medium",
    )

    response = client.complete(
        role="planner",
        system_prompt="Return a result.",
        user_prompt="Do the task.",
    )

    assert response.content == "ok"
    assert CapturingHttpxClient.last_request_json["model"] == "gpt-5.4-medium"
