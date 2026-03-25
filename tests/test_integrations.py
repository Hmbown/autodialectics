"""Integration and capability-gating tests."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from autodialectics.contract.compiler import ContractCompiler
from autodialectics.evolution.gepa_optimizer import ChampionChallengerManager
from autodialectics.exploration.rlm_explorer import ContextExplorer
from autodialectics.routing.cliproxy import ModelClient, build_model_client
from autodialectics.schemas import AssetKind, AssetRef, EvidenceBundle, EvidenceItem, TaskDomain, TaskSubmission
from autodialectics.settings import Settings


class SettingsStub:
    def __init__(self, base_url: str, api_key: str = "") -> None:
        self.cliproxy_base_url = base_url
        self.cliproxy_api_key = api_key


def test_settings_default_to_local_hermes_api() -> None:
    settings = Settings()
    assert settings.cliproxy_base_url == "http://127.0.0.1:8642"


def test_build_model_client_respects_configured_base_url() -> None:
    client = build_model_client(SettingsStub("http://127.0.0.1:8642"))
    assert isinstance(client, ModelClient)
    assert client.base_url == "http://127.0.0.1:8642"
    assert client.offline is False


def test_context_explorer_falls_back_when_rlm_path_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "Iran Israel diplomacy sanctions missile strike " * 200
    submission = TaskSubmission(
        title="RLM fallback test",
        description="Ensure DSPy failures fall back to heuristic exploration.",
        domain=TaskDomain.RESEARCH,
        assets=[AssetRef(kind=AssetKind.INLINE_TEXT, text=text, label="brief.txt")],
    )
    contract = ContractCompiler().compile(submission)
    explorer = ContextExplorer(use_dspy_rlm=True, rlm_threshold_chars=1)

    fallback_item = EvidenceItem(
        asset_id="brief.txt",
        query="What is the main task and context?",
        source_path="brief.txt",
        excerpt="fallback evidence",
        rationale="heuristic fallback",
        weight=0.42,
    )

    def explode(*args, **kwargs):
        raise RuntimeError("dspy unavailable")

    monkeypatch.setattr(explorer, "_explore_with_dspy_rlm", explode)
    monkeypatch.setattr(explorer, "_explore_recursively", lambda loaded, query: [fallback_item])

    bundle = explorer.explore(contract)
    assert bundle.generated_with_rlm is False
    assert bundle.items
    assert bundle.items[0].excerpt == "fallback evidence"


def test_gepa_manager_falls_back_to_heuristic_when_gepa_unavailable(runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = ChampionChallengerManager(runtime.store)
    monkeypatch.setattr(manager, "_try_gepa_optimization", lambda *args, **kwargs: None)

    challenger = manager.create_challenger(
        reports=[
            {
                "submission": {"title": "Task", "description": "Desc"},
                "notes": ["Verification quality was weak"],
                "slop": {"unsupported_claims": 0.45},
                "unmet_criteria": ["verification", "verification"],
            }
        ],
        use_gepa=True,
    )

    assert challenger.generation == "heuristic"
    assert challenger.is_champion is False
    assert challenger.parent_id is not None


@pytest.mark.integration
def test_live_hermes_api_smoke() -> None:
    host = "127.0.0.1"
    port = 8642
    with socket.socket() as sock:
        sock.settimeout(1.0)
        if sock.connect_ex((host, port)) != 0:
            pytest.skip("Local Hermes API server not reachable on 127.0.0.1:8642")

    client = ModelClient(base_url="http://127.0.0.1:8642")
    response = client.complete(
        role="integration-smoke",
        system_prompt="Reply with exactly OK_AUTODIALECTICS_HERMES_API",
        user_prompt="test",
    )
    assert response.content.strip() == "OK_AUTODIALECTICS_HERMES_API"
