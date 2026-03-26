"""Tests for benchmark case loading and execution."""

import json
from pathlib import Path

import pytest

from autodialectics.schemas import BenchmarkCase


def test_benchmark_cases_load(tmp_path: Path) -> None:
    """All 5 benchmark JSON files in benchmarks/cases/ should load as valid BenchmarkCase."""
    # We test against the actual project benchmark files if they exist,
    # otherwise create temporary ones
    benchmark_dir = Path("benchmarks/cases")
    if not benchmark_dir.exists():
        # Use the test_settings fixture benchmark dir
        benchmark_dir = tmp_path / "cases"
        benchmark_dir.mkdir(parents=True, exist_ok=True)

        # Create 5 sample cases
        cases = [
            {
                "case_id": "code_fix_001",
                "is_canary": False,
                "submission": {"title": "Code fix", "description": "Fix a bug."},
                "expectation": {
                    "must_include": ["fix"],
                    "must_not_include": ["perfect"],
                },
            },
            {
                "case_id": "research_synth_001",
                "is_canary": False,
                "submission": {"title": "Research", "description": "Synthesize research."},
                "expectation": {
                    "must_include": ["claim"],
                    "must_not_include": ["groundbreaking"],
                },
            },
            {
                "case_id": "writing_argument_001",
                "is_canary": False,
                "submission": {"title": "Writing", "description": "Revise argument."},
                "expectation": {
                    "must_include": ["revision"],
                    "must_not_include": ["flawless"],
                },
            },
            {
                "case_id": "experiment_loop_001",
                "is_canary": False,
                "submission": {"title": "Experiment", "description": "Design experiment."},
                "expectation": {
                    "must_include": ["baseline"],
                    "must_not_include": ["definitive"],
                },
            },
            {
                "case_id": "canary_long_context_001",
                "is_canary": True,
                "submission": {
                    "title": "Canary",
                    "description": "Long context canary.",
                    "assets": [
                        {
                            "kind": "inline_text",
                            "text": "Ambiguous canary document.",
                            "label": "canary.txt",
                        }
                    ],
                },
                "expectation": {
                    "must_include": ["ambiguous"],
                    "must_not_include": ["guaranteed"],
                },
            },
        ]
        for case in cases:
            fp = benchmark_dir / f"{case['case_id']}.json"
            fp.write_text(json.dumps(case), encoding="utf-8")

    # Load and validate
    json_files = sorted(benchmark_dir.glob("*.json"))
    assert len(json_files) >= 5, f"Expected at least 5 cases, found {len(json_files)}"

    for fp in json_files[:5]:
        data = json.loads(fp.read_text(encoding="utf-8"))
        case = BenchmarkCase(**data)
        assert case.case_id
        assert case.submission.title


def test_benchmark_smoke(runtime, tmp_path: Path) -> None:
    """Benchmark runner should complete with offline model and persist benchmark metadata."""
    records = runtime.benchmark()
    assert len(records) > 0
    for record in records:
        assert record.run_id

    champion = runtime.evolution.ensure_default_champion()
    summary = champion.benchmark_summary
    assert summary["run_count"] == float(len(records))
    assert 0.0 <= summary["overall_score"] <= 1.0
    assert 0.0 <= summary["slop_composite"] <= 1.0
    assert summary["canary_passed"] in {0.0, 1.0}

    reports = runtime.store.recent_benchmark_reports()
    assert reports
    latest_report = reports[0]
    assert "submission" in latest_report
    assert latest_report["submission"]["title"]
    assert "slop" in latest_report
    assert isinstance(latest_report["slop"], dict)
