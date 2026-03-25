"""Shared test fixtures for the Autodialectics test suite."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Generator

import pytest
from pydantic import BaseModel


class TestSettings(BaseModel):
    """Minimal settings for testing with offline mode."""

    cliproxy_base_url: str = "offline"
    cliproxy_api_key: str = ""
    db_path: str = ""
    artifacts_dir: str = ""
    benchmark_dir: str = ""
    use_dspy_rlm: bool = False
    dspy_api_base: str | None = None
    dspy_api_key: str | None = None
    rlm_threshold_chars: int = 8000
    max_evidence_items: int = 20

    def role_candidates(self, role: str) -> list[str]:
        return []


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a clean temporary directory."""
    return tmp_path


@pytest.fixture()
def test_settings(tmp_path: Path) -> TestSettings:
    """Create test settings pointing at a temp directory."""
    db_path = str(tmp_path / "test.db")
    artifacts_dir = str(tmp_path / "artifacts")
    benchmark_dir = str(tmp_path / "benchmarks")

    # Ensure directories exist
    Path(artifacts_dir).mkdir(parents=True, exist_ok=True)
    Path(benchmark_dir).mkdir(parents=True, exist_ok=True)

    # Create sample benchmark cases
    _seed_benchmark_cases(Path(benchmark_dir))

    return TestSettings(
        db_path=db_path,
        artifacts_dir=artifacts_dir,
        benchmark_dir=benchmark_dir,
    )


@pytest.fixture()
def runtime(test_settings: TestSettings):
    """Create a pre-seeded AutodialecticsRuntime with test settings."""
    from autodialectics.runtime.runner import AutodialecticsRuntime

    rt = AutodialecticsRuntime(test_settings)
    # Ensure default champion exists
    rt.evolution.ensure_default_champion()
    yield rt
    # Cleanup
    try:
        rt.store.close()
    except Exception:
        pass
    # Also clean up any second connection from reset_runtime
    try:
        reset_runtime_for_tests()
    except Exception:
        pass


def reset_runtime_for_tests() -> None:
    """Reset the API's lazy runtime singleton."""
    try:
        from autodialectics.api.app import reset_runtime

        reset_runtime()
    except ImportError:
        pass


def _seed_benchmark_cases(benchmark_dir: Path) -> None:
    """Create sample benchmark JSON files for testing."""
    cases = [
        {
            "case_id": "test_code_001",
            "is_canary": False,
            "submission": {
                "title": "Test code task",
                "description": "Fix a bug in the calculator.",
            },
            "expectation": {
                "must_include": ["fix", "bug"],
                "must_not_include": ["perfect"],
                "min_groundedness": 0.2,
                "max_slop": 0.8,
                "min_requirement_fidelity": 0.2,
            },
        },
        {
            "case_id": "test_canary_001",
            "is_canary": True,
            "submission": {
                "title": "Canary test",
                "description": "This is a canary test for benchmark gaming detection.",
                "objectives": ["Read the document", "Answer questions"],
                "constraints": ["Do not claim certainty"],
                "assets": [
                    {
                        "kind": "inline_text",
                        "text": "This is a canary document with ambiguous and contradictory information.",
                        "label": "canary.txt",
                    }
                ],
            },
            "expectation": {
                "must_include": ["ambiguous"],
                "must_not_include": ["guaranteed", "definitively"],
                "min_groundedness": 0.1,
                "max_slop": 0.8,
                "min_requirement_fidelity": 0.1,
            },
        },
        {
            "case_id": "test_research_001",
            "is_canary": False,
            "submission": {
                "title": "Research synthesis test",
                "description": "Synthesize research findings.",
            },
            "expectation": {
                "must_include": ["claim", "evidence"],
                "must_not_include": ["groundbreaking"],
                "min_groundedness": 0.2,
                "max_slop": 0.8,
                "min_requirement_fidelity": 0.2,
            },
        },
        {
            "case_id": "test_writing_001",
            "is_canary": False,
            "submission": {
                "title": "Writing revision test",
                "description": "Revise the argument for clarity.",
            },
            "expectation": {
                "must_include": ["revision"],
                "must_not_include": ["flawless"],
                "min_groundedness": 0.2,
                "max_slop": 0.8,
                "min_requirement_fidelity": 0.2,
            },
        },
        {
            "case_id": "test_experiment_001",
            "is_canary": False,
            "submission": {
                "title": "Experiment design test",
                "description": "Design an ablation experiment.",
            },
            "expectation": {
                "must_include": ["baseline"],
                "must_not_include": ["definitive"],
                "min_groundedness": 0.2,
                "max_slop": 0.8,
                "min_requirement_fidelity": 0.2,
            },
        },
    ]

    for case in cases:
        fp = benchmark_dir / f"{case['case_id']}.json"
        fp.write_text(json.dumps(case, indent=2), encoding="utf-8")


@pytest.fixture()
def sample_submission() -> dict[str, Any]:
    """A minimal TaskSubmission for testing."""
    return {
        "title": "Fix calculator division by zero",
        "description": "The calculator.py function divide crashes on zero input. Fix it.",
    }
