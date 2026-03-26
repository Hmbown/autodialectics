"""Tests for the AutodialecticsRuntime."""

from pathlib import Path

import pytest

from autodialectics.schemas import PolicySnapshot, TaskSubmission


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
    """Run should create all expected artifact files and persist their paths."""
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

    info = runtime.inspect(record.run_id)
    assert info is not None
    artifact_paths = info["artifact_paths"]
    for name in expected_files:
        assert name in artifact_paths
        assert Path(artifact_paths[name]).exists()


def test_promote_returns_promoted_policy(runtime) -> None:
    """Promotion should return the promoted champion when challenger benchmarks win."""
    champion = runtime.evolution.ensure_default_champion()
    champion_data = runtime.store.get_policy(champion.policy_id)
    assert champion_data is not None
    champion_data["benchmark_summary"] = {
        "overall_score": 0.40,
        "slop_composite": 0.30,
        "canary_passed": 1.0,
    }
    runtime.store.save_policy(champion_data)

    challenger = PolicySnapshot(
        version=champion.version + 1,
        parent_id=champion.policy_id,
        surfaces=dict(champion.surfaces),
        benchmark_summary={
            "overall_score": 0.75,
            "slop_composite": 0.20,
            "canary_passed": 1.0,
        },
        is_champion=False,
        generation="heuristic",
    )
    runtime.store.save_policy(challenger.model_dump(mode="json"))

    promoted = runtime.promote(challenger.policy_id)
    assert promoted is not None
    assert promoted["policy_id"] == challenger.policy_id
    assert runtime.evolution.ensure_default_champion().policy_id == challenger.policy_id


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
