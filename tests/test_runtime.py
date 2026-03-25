"""Tests for the AutodialecticsRuntime."""

from pathlib import Path

import pytest

from autodialectics.schemas import TaskSubmission


def test_offline_smoke_run(runtime) -> None:
    """Full pipeline with offline model should complete without error."""
    sub = TaskSubmission(
        title="Smoke test",
        description="A simple offline smoke test.",
    )
    record = runtime.run(sub)
    assert record.run_id
    assert record.status in ("completed", "rejected", "failed")
    assert record.error is None, f"Run failed with error: {record.error}"


def test_artifact_emission(runtime, tmp_path: Path) -> None:
    """Run should create all expected artifact files."""
    sub = TaskSubmission(
        title="Artifact test",
        description="Verify artifact emission.",
    )
    record = runtime.run(sub)
    assert record.run_id

    run_dir = Path(runtime.settings.artifacts_dir) / record.run_id
    expected_files = [
        "evidence.json",
        "dialectic.json",
        "execution.json",
        "verification.json",
        "evaluation.json",
        "summary.md",
    ]
    for name in expected_files:
        artifact_path = run_dir / name
        assert artifact_path.exists(), f"Missing artifact: {name}"


def test_benchmark_smoke_run(runtime, tmp_path: Path) -> None:
    """Benchmark with offline model should complete without error."""
    records = runtime.benchmark()
    assert len(records) > 0, "Should have run at least one benchmark case"
    for r in records:
        assert r.run_id


def test_compile_task(runtime) -> None:
    """compile_task shortcut should work."""
    sub = TaskSubmission(
        title="Compile test",
        description="Test the compile shortcut.",
    )
    contract = runtime.compile_task(sub)
    assert contract.title == "Compile test"
    assert contract.source_hash
    assert contract.domain
    assert len(contract.evaluation_rubric) > 0
