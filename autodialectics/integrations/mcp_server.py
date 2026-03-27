"""MCP server exposing the Autodialectics runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from autodialectics.schemas import TaskSubmission
from autodialectics.settings import Settings

SERVER_INSTRUCTIONS = (
    "Use Autodialectics when you want a structured contract, evidence bundle, "
    "dialectical planning, verification, evaluation, or benchmark/policy flows. "
    "Prefer compile_task before run_task when you want to inspect the contract first."
)

server = FastMCP(
    name="Autodialectics",
    instructions=SERVER_INSTRUCTIONS,
)


def _load_runtime(config_path: str | None = None):
    from autodialectics.runtime.runner import AutodialecticsRuntime

    settings = Settings.load(config_path)
    return AutodialecticsRuntime(settings)


def _resolved_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _ensure_within(path: Path, *allowed_roots: Path) -> Path:
    for root in allowed_roots:
        root_path = root.resolve()
        try:
            path.relative_to(root_path)
            return path
        except ValueError:
            continue

    allowed_display = ", ".join(str(root.resolve()) for root in allowed_roots)
    raise ValueError(f"Path must stay within one of: {allowed_display}")


def _load_submission(task_file: str) -> TaskSubmission:
    path = _ensure_within(_resolved_path(task_file), Path.cwd())
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return TaskSubmission(**data)


def _run_record_to_dict(record: Any) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "contract_id": record.contract_id,
        "domain": record.domain,
        "policy_id": record.policy_id,
        "status": record.status,
        "decision": record.decision,
        "overall_score": record.overall_score,
        "slop_composite": record.slop_composite,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "summary": record.summary,
        "error": record.error,
    }


@server.tool(
    description="Check that the Autodialectics MCP server is reachable.",
    structured_output=True,
)
def health(config_path: str | None = None) -> dict[str, Any]:
    settings = Settings.load(config_path)
    return {
        "status": "ok",
        "server": "autodialectics-mcp",
        "config_path": config_path,
        "cliproxy_base_url": settings.cliproxy_base_url,
        "db_path": settings.db_path,
        "artifacts_dir": settings.artifacts_dir,
    }


@server.tool(
    description="Initialize the database and ensure a default champion policy exists.",
    structured_output=True,
)
def init_runtime(config_path: str | None = None) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    champion = runtime.evolution.ensure_default_champion()
    return {
        "status": "initialized",
        "policy_id": champion.policy_id,
        "db_path": runtime.settings.db_path,
        "artifacts_dir": runtime.settings.artifacts_dir,
    }


@server.tool(
    description="Compile a task JSON file into a contract without executing the full pipeline.",
    structured_output=True,
)
def compile_task(task_file: str, config_path: str | None = None) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    submission = _load_submission(task_file)
    contract = runtime.compile_task(submission)
    return contract.model_dump(mode="json")


@server.tool(
    description="Execute the full Autodialectics pipeline for a task JSON file.",
    structured_output=True,
)
def run_task(
    task_file: str,
    policy_id: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    submission = _load_submission(task_file)
    record = runtime.run(submission, policy_id=policy_id)
    return _run_record_to_dict(record)


@server.tool(
    description="Run the benchmark suite and return summarized benchmark records.",
    structured_output=True,
)
def benchmark(
    suite_dir: str | None = None,
    policy_id: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    records = runtime.benchmark(suite_dir=suite_dir, policy_id=policy_id)
    return {
        "total_cases": len(records),
        "results": [_run_record_to_dict(record) for record in records],
    }


@server.tool(
    description="Inspect a run manifest and its recorded artifact paths.",
    structured_output=True,
)
def inspect_run(run_id: str, config_path: str | None = None) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    result = runtime.inspect(run_id)
    if result is None:
        raise ValueError(f"Run not found: {run_id}")
    return result


@server.tool(
    description="Read a stored artifact for a run by artifact filename.",
    structured_output=True,
)
def read_artifact(
    run_id: str,
    artifact_name: str,
    config_path: str | None = None,
) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    info = runtime.inspect(run_id)
    if info is None:
        raise ValueError(f"Run not found: {run_id}")

    artifact_paths = info.get("artifact_paths", {})
    path = artifact_paths.get(artifact_name)
    if path is None:
        raise ValueError(f"Artifact not found for run {run_id}: {artifact_name}")

    artifact_root = _resolved_path(runtime.settings.artifacts_dir)
    artifact_path = _ensure_within(_resolved_path(path), artifact_root)
    if not artifact_path.exists():
        raise FileNotFoundError(f"Artifact path missing on disk: {artifact_path}")

    suffix = artifact_path.suffix.lower()
    content = artifact_path.read_text(encoding="utf-8")
    parsed: Any = json.loads(content) if suffix == ".json" else content

    return {
        "run_id": run_id,
        "artifact_name": artifact_name,
        "path": str(artifact_path),
        "content": parsed,
    }


@server.tool(
    description="Create a challenger policy from recent benchmark reports.",
    structured_output=True,
)
def evolve_policy(use_gepa: bool = True, config_path: str | None = None) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    policy_id = runtime.evolve(use_gepa=use_gepa)
    if not policy_id:
        return {"status": "no_reports", "policy_id": ""}
    return {"status": "created", "policy_id": policy_id}


@server.tool(
    description="Promote a challenger policy to champion when comparison rules allow it.",
    structured_output=True,
)
def promote_policy(policy_id: str, config_path: str | None = None) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    promoted = runtime.promote(policy_id)
    if promoted is None:
        return {"status": "denied", "policy_id": policy_id}
    return {"status": "promoted", "policy": promoted}


@server.tool(
    description="Rollback to the previous champion policy.",
    structured_output=True,
)
def rollback_policy(config_path: str | None = None) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    policy_id = runtime.rollback()
    return {"status": "rolled_back", "policy_id": policy_id}


@server.tool(
    description="Replay a stored run manifest with an optional replacement policy id.",
    structured_output=True,
)
def replay_run(
    run_id: str,
    policy_id: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    runtime = _load_runtime(config_path)
    record = runtime.replay(run_id, policy_id=policy_id)
    if record is None:
        raise ValueError(f"Run not found: {run_id}")
    return _run_record_to_dict(record)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
