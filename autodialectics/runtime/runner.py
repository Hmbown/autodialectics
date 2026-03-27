"""Autodialectics runtime: orchestrates the full pipeline."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autodialectics.contract.compiler import ContractCompiler
from autodialectics.dialectic.engine import AdvanceGate, DialecticalPlanner
from autodialectics.evaluation.slop import RunEvaluator
from autodialectics.evolution.gepa_optimizer import ChampionChallengerManager
from autodialectics.execution.adapters import AdapterRegistry
from autodialectics.exploration.rlm_explorer import ContextExplorer
from autodialectics.routing.cliproxy import ModelClient, build_model_client
from autodialectics.schemas import (
    AdvanceAction,
    BenchmarkCase,
    EvidenceBundle,
    ExecutionArtifact,
    RunEvaluation,
    RunManifest,
    RunStatus,
    TaskSubmission,
    TaskContract,
    VerificationVerdict,
)
from autodialectics.storage.files import ArtifactStore
from autodialectics.storage.sqlite import SqliteStore

logger = logging.getLogger(__name__)


@dataclass
class RunRecord:
    """Lightweight record of a completed or in-progress run."""

    run_id: str
    contract_id: str
    domain: str
    policy_id: str
    status: str
    decision: str | None = None
    overall_score: float = 0.0
    slop_composite: float = 0.0
    started_at: str = ""
    ended_at: str = ""
    summary: str = ""
    error: str | None = None


class AutodialecticsRuntime:
    """Top-level runtime that wires together all pipeline components."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.store = SqliteStore(settings.db_path)
        self.artifacts = ArtifactStore(settings.artifacts_dir)
        self.model_client = build_model_client(settings)
        self.compiler = ContractCompiler()
        self.explorer = ContextExplorer(
            use_dspy_rlm=getattr(settings, "use_dspy_rlm", False),
            max_evidence_items=getattr(settings, "max_evidence_items", 20),
            rlm_threshold_chars=getattr(settings, "rlm_threshold_chars", 8000),
            dspy_settings=settings,
        )
        self.planner = DialecticalPlanner(model_client=self.model_client)
        self.evaluator = RunEvaluator()
        self.gate = AdvanceGate()
        self.adapters = AdapterRegistry()
        self.evolution = ChampionChallengerManager(self.store, settings=settings)

    # ── Shortcuts ─────────────────────────────────────────────────────

    def compile_task(self, submission: TaskSubmission) -> TaskContract:
        """Compile a submission into a task contract."""
        return self.compiler.compile(submission)

    # ── Full pipeline run ─────────────────────────────────────────────

    def run(
        self,
        submission: TaskSubmission,
        policy_id: str | None = None,
        benchmark_case: BenchmarkCase | None = None,
    ) -> RunRecord:
        """Execute the full pipeline: compile → explore → plan → execute → verify → evaluate → decide.

        Returns a RunRecord with all results.
        """
        started_at = datetime.now(timezone.utc)
        run_id = f"run_{started_at.strftime('%Y%m%d%H%M%S')}_{id(submission) % 10000:04d}"

        # Resolve policy
        if policy_id:
            policy_data = self.store.get_policy(policy_id)
            policy_surfaces = (
                policy_data.get("surfaces", {}) if policy_data else {}
            )
        else:
            champion = self.evolution.ensure_default_champion()
            policy_surfaces = champion.surfaces
            policy_id = champion.policy_id

        manifest = RunManifest(
            run_id=run_id,
            contract_id="",
            domain=submission.domain or self.compiler.infer_domain(submission),
            policy_id=policy_id,
            status=RunStatus.RUNNING,
            started_at=started_at,
        )

        try:
            # 1. Compile
            contract = self.compiler.compile(submission)
            manifest.contract_id = contract.contract_id
            manifest.domain = contract.domain
            self.store.save_run_manifest(manifest.model_dump(mode="json"))

            # 2. Explore
            evidence = self.explorer.explore(contract)
            self._record_json_artifact(manifest, "evidence.json", evidence)

            # 3. Plan (dialectic)
            dialectic = self.planner.plan(contract, evidence, policy_surfaces)
            self._record_json_artifact(manifest, "dialectic.json", dialectic)

            # 4. Execute
            adapter = self.adapters.for_domain(contract.domain)
            execution = adapter.execute(
                contract, evidence, dialectic, self.model_client, policy_surfaces
            )
            self._record_json_artifact(manifest, "execution.json", execution)
            manifest.adapter_name = adapter.name

            # 5. Verify
            verification = self.evaluator.verify(
                contract, execution, evidence=evidence
            )
            self._record_json_artifact(manifest, "verification.json", verification)

            # 6. Evaluate
            # Get prior champion score for regression detection
            champion = self.evolution.ensure_default_champion()
            prior_score = champion.benchmark_summary.get("overall_score", 0.0)

            evaluation = self.evaluator.evaluate_run(
                contract,
                execution,
                dialectic,
                verification,
                evidence=evidence,
                prior_champion_score=prior_score,
            )
            self._record_json_artifact(manifest, "evaluation.json", evaluation)

            # 7. Decide
            decision = self.gate.decide(verification, evaluation, prior_score)
            manifest.decision = decision.action
            manifest.status = (
                RunStatus.COMPLETED
                if decision.action == AdvanceAction.ACCEPT
                else RunStatus.REJECTED
            )

            # 8. Save summary
            summary = self._render_summary(
                contract, evidence, dialectic, execution, verification, evaluation, decision
            )
            manifest.summary = summary
            self._record_markdown_artifact(manifest, "summary.md", summary)

            # 9. Save benchmark if this is a benchmark run
            if benchmark_case:
                benchmark_report = self._build_benchmark_report(
                    run_id, benchmark_case, evaluation, verification
                )
                self.store.save_benchmark_report(run_id, benchmark_report)
                self._record_json_artifact(
                    manifest, "benchmark_report.json", benchmark_report
                )

            ended_at = datetime.now(timezone.utc)
            manifest.ended_at = ended_at
            self.store.save_run_manifest(manifest.model_dump(mode="json"))

            return RunRecord(
                run_id=run_id,
                contract_id=contract.contract_id,
                domain=contract.domain.value,
                policy_id=policy_id,
                status=manifest.status.value,
                decision=decision.action.value,
                overall_score=evaluation.overall_score,
                slop_composite=evaluation.slop.composite,
                started_at=started_at.isoformat(),
                ended_at=ended_at.isoformat(),
                summary=summary,
            )

        except Exception as exc:
            logger.exception("Run %s failed: %s", run_id, exc)
            manifest.status = RunStatus.FAILED
            manifest.ended_at = datetime.now(timezone.utc)
            manifest.summary = f"Run failed: {exc}"
            self.store.save_run_manifest(manifest.model_dump(mode="json"))

            return RunRecord(
                run_id=run_id,
                contract_id=manifest.contract_id,
                domain=manifest.domain.value,
                policy_id=policy_id or "unknown",
                status="failed",
                error=str(exc),
                started_at=started_at.isoformat(),
                ended_at=manifest.ended_at.isoformat(),
            )

    # ── Benchmarking ──────────────────────────────────────────────────

    def benchmark(
        self,
        suite_dir: str | Path | None = None,
        policy_id: str | None = None,
    ) -> list[RunRecord]:
        """Run all benchmark cases from a suite directory."""
        if suite_dir is None:
            suite_dir = getattr(self.settings, "benchmark_dir", "benchmarks/cases")

        cases = self._load_benchmark_cases(Path(suite_dir))
        if not cases:
            logger.warning("No benchmark cases found in %s", suite_dir)
            return []

        records: list[RunRecord] = []
        canary_passed = True

        for case in cases:
            logger.info("Running benchmark case: %s", case.case_id)
            record = self.run(
                case.submission,
                policy_id=policy_id,
                benchmark_case=case,
            )
            records.append(record)

            # Check canary
            if case.is_canary and case.expectation:
                score = self._score_benchmark_case(case, record)
                if score < 0.5:
                    canary_passed = False
                    logger.warning(
                        "Canary case %s failed (score=%.2f)",
                        case.case_id,
                        score,
                    )

        benchmark_policy_id = policy_id
        if benchmark_policy_id is None:
            benchmark_policy_id = self.evolution.ensure_default_champion().policy_id

        if benchmark_policy_id and records:
            self._update_policy_benchmark_summary(
                benchmark_policy_id,
                records,
                canary_passed=canary_passed,
            )

        logger.info(
            "Benchmark complete: %d cases, canary_passed=%s",
            len(records),
            canary_passed,
        )
        return records

    # ── Evolution ─────────────────────────────────────────────────────

    def evolve(self, use_gepa: bool = True) -> str:
        """Create a challenger policy from recent benchmark reports.

        Returns the challenger policy_id.
        """
        reports = self.store.recent_benchmark_reports()
        if not reports:
            logger.info("No benchmark reports available for evolution")
            return ""

        challenger = self.evolution.create_challenger(
            reports, use_gepa=use_gepa
        )
        logger.info("Created challenger: %s", challenger.policy_id)
        return challenger.policy_id

    def promote(self, challenger_id: str) -> dict[str, Any] | None:
        """Promote a challenger to champion."""
        challenger_data = self.store.get_policy(challenger_id)
        if not challenger_data:
            logger.error("Challenger %s not found", challenger_id)
            return None

        champion = self.evolution.ensure_default_champion()
        challenger_summary = challenger_data.get("benchmark_summary", {})

        champion_score = champion.benchmark_summary.get("overall_score", 0.0)
        challenger_score = challenger_summary.get("overall_score", 0.0)
        champion_slop = champion.benchmark_summary.get("slop_composite", 0.5)
        challenger_slop = challenger_summary.get("slop_composite", 0.5)
        canary_passed = challenger_summary.get("canary_passed", 0.0) >= 0.5

        decision = self.evolution.compare(
            champion_score,
            challenger_score,
            champion_slop,
            challenger_slop,
            canary_passed=canary_passed,
        )

        if decision.promote:
            promoted = self.evolution.promote(challenger_id, decision)
            logger.info("Promoted %s to champion", challenger_id)
            return promoted.model_dump(mode="json")

        logger.info("Promotion denied: %s", decision.rationale)
        return None

    def rollback(self) -> str:
        """Rollback to previous champion. Returns the champion policy_id."""
        champion = self.evolution.rollback()
        logger.info("Rolled back to champion: %s", champion.policy_id)
        return champion.policy_id

    # ── Inspection ────────────────────────────────────────────────────

    def inspect(self, run_id: str) -> dict[str, Any] | None:
        """Get run info by run_id."""
        manifest = self.store.get_run_manifest(run_id)
        if manifest is None:
            return None

        artifact_paths = self.store.get_artifact_paths(run_id)
        return {
            "manifest": manifest,
            "artifact_paths": artifact_paths,
        }

    def replay(
        self, run_id: str, policy_id: str | None = None
    ) -> RunRecord | None:
        """Replay a run with the same submission but potentially different policy."""
        manifest = self.store.get_run_manifest(run_id)
        if manifest is None:
            logger.error("Run %s not found", run_id)
            return None

        # We need the original contract to reconstruct the submission
        # For now, return the stored manifest info
        logger.info(
            "Replay requested for run %s (policy=%s)",
            run_id,
            policy_id,
        )
        # Full replay would require storing the original submission
        # This is a placeholder that returns the stored record
        return RunRecord(
            run_id=run_id,
            contract_id=manifest.get("contract_id", ""),
            domain=manifest.get("domain", "generic"),
            policy_id=policy_id or manifest.get("policy_id", ""),
            status=manifest.get("status", "unknown"),
            decision=manifest.get("decision"),
            summary="Replay: stored manifest retrieved.",
        )

    # ── Internal helpers ──────────────────────────────────────────────

    def _record_json_artifact(
        self,
        manifest: RunManifest,
        name: str,
        data: Any,
    ) -> str:
        """Write a JSON artifact and persist its path on the manifest and in SQLite."""
        path = self.artifacts.write_json(manifest.run_id, name, data)
        path_str = str(path)
        manifest.artifact_paths[name] = path_str
        self.store.save_artifact_path(manifest.run_id, name, path_str)
        return path_str

    def _record_markdown_artifact(
        self,
        manifest: RunManifest,
        name: str,
        text: str,
    ) -> str:
        """Write a markdown artifact and persist its path on the manifest and in SQLite."""
        path = self.artifacts.write_markdown(manifest.run_id, name, text)
        path_str = str(path)
        manifest.artifact_paths[name] = path_str
        self.store.save_artifact_path(manifest.run_id, name, path_str)
        return path_str

    def _update_policy_benchmark_summary(
        self,
        policy_id: str,
        records: list[RunRecord],
        *,
        canary_passed: bool,
    ) -> None:
        """Persist aggregate benchmark results onto the policy that was benchmarked."""
        policy_data = self.store.get_policy(policy_id)
        if policy_data is None or not records:
            return

        count = len(records)
        policy_data["benchmark_summary"] = {
            "overall_score": sum(r.overall_score for r in records) / count,
            "slop_composite": sum(r.slop_composite for r in records) / count,
            "accepted_rate": sum(1.0 for r in records if r.decision == AdvanceAction.ACCEPT.value) / count,
            "run_count": float(count),
            "canary_passed": 1.0 if canary_passed else 0.0,
        }
        self.store.save_policy(policy_data)

    def _render_summary(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: Any,
        execution: ExecutionArtifact,
        verification: Any,
        evaluation: RunEvaluation,
        decision: Any,
    ) -> str:
        """Render a markdown summary of the run."""
        lines = [
            f"# Run Summary: {contract.title}",
            "",
            f"**Domain:** {contract.domain.value}",
            f"**Verdict:** {verification.verdict.value}",
            f"**Score:** {evaluation.overall_score:.2f}",
            f"**Slop:** {evaluation.slop.composite:.2f}",
            f"**Decision:** {decision.action.value}",
            "",
            "## Facts",
            "",
            f"- Verification: {verification.summary}",
            f"- Task success: {evaluation.task_success:.2f}",
            f"- Groundedness: {evaluation.groundedness:.2f}",
            f"- Requirement fidelity: {evaluation.requirement_fidelity:.2f}",
            "",
            "## Inferences",
            "",
        ]

        for step in dialectic.synthesis_steps[:5]:
            lines.append(f"- {step}")

        if evaluation.notes:
            lines += ["", "## Evaluation Notes", ""]
            for note in evaluation.notes:
                lines.append(f"- {note}")

        lines += ["", "## Unresolved", ""]
        for q in dialectic.unresolved_questions:
            lines.append(f"- {q}")

        if verification.independent_findings:
            lines += ["", "## Independent Findings", ""]
            for finding in verification.independent_findings:
                lines.append(f"- {finding}")

        lines.append("")
        return "\n".join(lines)

    def _load_benchmark_cases(self, suite_dir: Path) -> list[BenchmarkCase]:
        """Load BenchmarkCase JSON files from a directory."""
        cases: list[BenchmarkCase] = []
        if not suite_dir.exists():
            logger.warning("Benchmark suite directory not found: %s", suite_dir)
            return cases

        for fp in sorted(suite_dir.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                case = BenchmarkCase(**data)
                cases.append(case)
            except Exception as exc:
                logger.warning(
                    "Failed to load benchmark case %s: %s", fp, exc
                )

        return cases

    def _score_benchmark_case(
        self, case: BenchmarkCase, record: RunRecord
    ) -> float:
        """Score a benchmark case against expectations."""
        expect = case.expectation
        score = 1.0
        benchmark_text = self._benchmark_text(record).lower()

        # Check must_include
        for phrase in expect.must_include:
            if phrase.lower() not in benchmark_text:
                score -= 0.2

        # Check must_not_include
        for phrase in expect.must_not_include:
            if self._contains_forbidden_benchmark_phrase(benchmark_text, phrase.lower()):
                score -= 0.2

        # Check groundedness
        # (We'd need the full evaluation for this; approximate from record)
        # Check max_slop
        if record.slop_composite > expect.max_slop:
            score -= 0.3

        # Check requirement_fidelity
        # (Approximate; would need full evaluation record)

        return max(0.0, min(score, 1.0))

    def _benchmark_text(self, record: RunRecord) -> str:
        """Load the richest available text for benchmark phrase checks."""
        text_parts = [record.summary or ""]
        run_dir = self.artifacts.base / record.run_id

        execution_path = run_dir / "execution.json"
        if execution_path.is_file():
            try:
                payload = json.loads(execution_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                text_parts.append(str(payload.get("summary", "")))
                text_parts.append(str(payload.get("output_text", "")))

        summary_path = run_dir / "summary.md"
        if summary_path.is_file():
            text_parts.append(summary_path.read_text(encoding="utf-8"))

        return "\n".join(part for part in text_parts if part)

    def _contains_forbidden_benchmark_phrase(self, text: str, phrase: str) -> bool:
        """Return True only when a forbidden phrase is used positively, not quoted as a warning."""
        windows = [segment.strip() for segment in text.splitlines() if segment.strip()]
        ignore_markers = (
            "must_not_include",
            "avoid",
            "discourag",
            "do not use",
            "do not claim",
            "certainty markers such as",
            "include terms like",
        )
        for window in windows:
            lowered = window.lower()
            if phrase not in lowered:
                continue
            if any(marker in lowered for marker in ignore_markers):
                continue
            return True
        return False

    def _build_benchmark_report(
        self,
        run_id: str,
        case: BenchmarkCase,
        evaluation: RunEvaluation,
        verification: Any,
    ) -> dict[str, Any]:
        """Build a benchmark report dict for storage."""
        return {
            "run_id": run_id,
            "case_id": case.case_id,
            "is_canary": case.is_canary,
            "submission": case.submission.model_dump(mode="json"),
            "overall_score": evaluation.overall_score,
            "slop": evaluation.slop.model_dump(mode="json"),
            "slop_composite": evaluation.slop.composite,
            "task_success": evaluation.task_success,
            "groundedness": evaluation.groundedness,
            "requirement_fidelity": evaluation.requirement_fidelity,
            "verdict": verification.verdict.value,
            "accepted": evaluation.accepted,
            "notes": evaluation.notes,
            "unmet_criteria": verification.unmet_criteria,
            "expectation": case.expectation.model_dump(mode="json"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
