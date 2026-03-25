"""FastAPI application for the Autodialectics pipeline."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel

from autodialectics.schemas import (
    PolicySnapshot,
    RunManifest,
    TaskContract,
    TaskSubmission,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Autodialectics API",
    version="0.1.0",
    description=(
        "Agentic harness API for keeping research-oriented runs on-task with "
        "contracts, evidence, dialectics, verification, and anti-slop gates"
    ),
)

router = APIRouter()

# ── Lazy runtime singleton ──────────────────────────────────────────

_runtime_instance = None


def _get_settings() -> Any:
    from autodialectics.settings import Settings

    return Settings.load()


def get_runtime() -> Any:
    """Dependency that provides a lazy singleton of AutodialecticsRuntime."""
    global _runtime_instance
    if _runtime_instance is None:
        from autodialectics.runtime.runner import AutodialecticsRuntime

        settings = _get_settings()
        _runtime_instance = AutodialecticsRuntime(settings)
        logger.info("Runtime initialized (lazy singleton)")
    return _runtime_instance


def reset_runtime() -> None:
    """Reset the runtime singleton (useful for testing)."""
    global _runtime_instance
    _runtime_instance = None


# ── Request / response models ───────────────────────────────────────


class RunRequest(BaseModel):
    submission: TaskSubmission
    policy_id: str | None = None


class BenchmarkRunRequest(BaseModel):
    suite_dir: str | None = None
    policy_id: str | None = None


class EvolveRequest(BaseModel):
    use_gepa: bool = True


class HealthResponse(BaseModel):
    status: str


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/tasks/compile", response_model=TaskContract)
async def compile_task(
    submission: TaskSubmission,
    runtime: Any = Depends(get_runtime),
) -> TaskContract:
    """Compile a TaskSubmission into a TaskContract."""
    contract = runtime.compile_task(submission)
    return contract


@router.post("/runs", response_model=RunManifest)
async def create_run(
    request: RunRequest,
    runtime: Any = Depends(get_runtime),
) -> RunManifest:
    """Create and execute a new run."""
    record = runtime.run(
        request.submission,
        policy_id=request.policy_id,
    )
    if record.error:
        raise HTTPException(status_code=500, detail=record.error)

    manifest = runtime.store.get_run_manifest(record.run_id)
    if manifest is None:
        raise HTTPException(status_code=500, detail="Run manifest not found after creation")
    return RunManifest(**manifest)


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Get run manifest and artifact paths by run_id."""
    info = runtime.inspect(run_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return info


@router.post("/benchmarks/run")
async def run_benchmark(
    request: BenchmarkRunRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Run the benchmark suite and return a summary."""
    records = runtime.benchmark(
        suite_dir=request.suite_dir,
        policy_id=request.policy_id,
    )
    summary = {
        "total_cases": len(records),
        "results": [
            {
                "run_id": r.run_id,
                "status": r.status,
                "overall_score": r.overall_score,
                "slop_composite": r.slop_composite,
                "decision": r.decision,
                "error": r.error,
            }
            for r in records
        ],
    }
    return summary


@router.post("/policies/evolve", response_model=PolicySnapshot)
async def evolve_policy(
    request: EvolveRequest,
    runtime: Any = Depends(get_runtime),
) -> PolicySnapshot:
    """Create a challenger policy via evolution."""
    policy_id = runtime.evolve(use_gepa=request.use_gepa)
    if not policy_id:
        raise HTTPException(
            status_code=400,
            detail="No benchmark reports available for evolution",
        )
    policy_data = runtime.store.get_policy(policy_id)
    if policy_data is None:
        raise HTTPException(status_code=500, detail="Challenger policy not found after creation")
    return PolicySnapshot(**policy_data)


@router.post("/policies/{policy_id}/promote", response_model=PolicySnapshot)
async def promote_policy(
    policy_id: str,
    runtime: Any = Depends(get_runtime),
) -> PolicySnapshot:
    """Promote a challenger policy to champion."""
    result = runtime.promote(policy_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Policy {policy_id} not found or promotion denied",
        )
    # Return the current champion
    champion = runtime.evolution.ensure_default_champion()
    return champion


@router.post("/policies/rollback", response_model=PolicySnapshot)
async def rollback_policy(
    runtime: Any = Depends(get_runtime),
) -> PolicySnapshot:
    """Rollback to the previous champion policy."""
    policy_id = runtime.rollback()
    policy_data = runtime.store.get_policy(policy_id)
    if policy_data is None:
        raise HTTPException(status_code=500, detail="Rollback failed")
    return PolicySnapshot(**policy_data)


app.include_router(router)
