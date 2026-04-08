"""Pydantic v2 schemas for the Autodialectics pipeline."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from autodialectics.schemas.enums import (
    AdvanceAction,
    AssetKind,
    RunStatus,
    TaskDomain,
    VerificationVerdict,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Asset ────────────────────────────────────────────────────────────

class AssetRef(BaseModel):
    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: AssetKind
    label: str | None = None
    location: str | None = None
    text: str | None = None


# ── Task input ───────────────────────────────────────────────────────

class TaskSubmission(BaseModel):
    title: str
    description: str = ""
    domain: TaskDomain | None = None
    objectives: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    forbidden_shortcuts: list[str] = Field(default_factory=list)
    assets: list[AssetRef] = Field(default_factory=list)
    workspace_root: str | None = None
    verification_commands: list[str] = Field(default_factory=list)
    max_repair_attempts: int | None = None


# ── Compiled contract ────────────────────────────────────────────────

class TaskContract(BaseModel):
    contract_id: str = Field(default_factory=lambda: str(uuid4()))
    source_hash: str
    title: str
    domain: TaskDomain
    objectives: list[str]
    constraints: list[str]
    deliverables: list[str]
    acceptance_criteria: list[str]
    forbidden_shortcuts: list[str]
    relevant_assets: list[AssetRef]
    workspace_root: str | None = None
    verification_commands: list[str] = Field(default_factory=list)
    max_repair_attempts: int = 1
    evaluation_rubric: dict[str, float]
    compiler_notes: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# Task Contract: {self.title}",
            "",
            f"**Contract ID:** `{self.contract_id}`",
            f"**Domain:** {self.domain.value}",
            f"**Source hash:** `{self.source_hash}`",
            "",
            "## Objectives",
            "",
        ]
        for i, obj in enumerate(self.objectives, 1):
            lines.append(f"{i}. {obj}")

        if self.constraints:
            lines += ["", "## Constraints", ""]
            for i, c in enumerate(self.constraints, 1):
                lines.append(f"{i}. {c}")

        if self.deliverables:
            lines += ["", "## Deliverables", ""]
            for i, d in enumerate(self.deliverables, 1):
                lines.append(f"{i}. {d}")

        if self.acceptance_criteria:
            lines += ["", "## Acceptance Criteria", ""]
            for i, a in enumerate(self.acceptance_criteria, 1):
                lines.append(f"{i}. {a}")

        if self.forbidden_shortcuts:
            lines += ["", "## Forbidden Shortcuts", ""]
            for i, f in enumerate(self.forbidden_shortcuts, 1):
                lines.append(f"{i}. {f}")

        if self.relevant_assets:
            lines += ["", "## Relevant Assets", ""]
            for asset in self.relevant_assets:
                label = asset.label or asset.asset_id
                loc = asset.location or "(inline)"
                lines.append(f"- **{label}** ({asset.kind.value}): {loc}")

        if self.workspace_root:
            lines += ["", "## Workspace", ""]
            lines.append(f"- Workspace root: {self.workspace_root}")

        if self.verification_commands:
            lines += ["", "## Verification Commands", ""]
            for command in self.verification_commands:
                lines.append(f"- `{command}`")

        lines += ["", "## Repair Budget", ""]
        lines.append(f"- Max repair attempts: {self.max_repair_attempts}")

        if self.evaluation_rubric:
            lines += ["", "## Evaluation Rubric", ""]
            for key, weight in self.evaluation_rubric.items():
                lines.append(f"- {key}: {weight}")

        if self.compiler_notes:
            lines += ["", "## Compiler Notes", ""]
            for note in self.compiler_notes:
                lines.append(f"- {note}")

        lines.append("")
        return "\n".join(lines)


# ── Evidence ─────────────────────────────────────────────────────────

class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid4().hex[:8]}")
    asset_id: str
    query: str
    source_path: str
    excerpt: str
    rationale: str
    weight: float


class EvidenceBundle(BaseModel):
    summary: str
    generated_with_rlm: bool = False
    items: list[EvidenceItem] = Field(default_factory=list)
    coverage_map: dict[str, list[str]] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)


# ── Dialectic ────────────────────────────────────────────────────────

class ObjectionRecord(BaseModel):
    objection_id: str = Field(default_factory=lambda: f"obj_{uuid4().hex[:8]}")
    claim: str
    objection: str
    severity: float = 0.5
    accepted: bool | None = None
    disposition: str | None = None


class DialecticArtifact(BaseModel):
    thesis: str
    thesis_steps: list[str] = Field(default_factory=list)
    antithesis_summary: str = ""
    synthesis: str
    synthesis_steps: list[str] = Field(default_factory=list)
    objection_ledger: list[ObjectionRecord] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


# ── Execution ────────────────────────────────────────────────────────

class ExecutionArtifact(BaseModel):
    summary: str = ""
    output_text: str = ""
    patches: list[str] = Field(default_factory=list)
    test_results: list[str] = Field(default_factory=list)
    created_files: list[str] = Field(default_factory=list)
    tool_log: list[str] = Field(default_factory=list)
    declared_uncertainties: list[str] = Field(default_factory=list)
    structured_output: dict = Field(default_factory=dict)
    status: str = "completed"


# ── Verification ─────────────────────────────────────────────────────

class VerificationCheck(BaseModel):
    criterion: str
    status: str = "fail"
    notes: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    independent: bool = True


class VerificationReport(BaseModel):
    verdict: VerificationVerdict = VerificationVerdict.FAIL
    summary: str = ""
    checks: list[VerificationCheck] = Field(default_factory=list)
    unmet_criteria: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    fresh_context_notes: str = ""
    cited_evidence_ids: list[str] = Field(default_factory=list)
    independent_findings: list[str] = Field(default_factory=list)


# ── Slop & evaluation ───────────────────────────────────────────────

class SlopMetrics(BaseModel):
    verbosity_without_gain: float = 0
    repetition_without_progress: float = 0
    unsupported_claims: float = 0
    requirement_drift: float = 0
    fake_completion: float = 0
    self_verification_bias: float = 0
    benchmark_gaming: float = 0
    shallow_novelty: float = 0
    context_contamination: float = 0
    refusal_to_surface_uncertainty: float = 0
    tool_abuse: float = 0
    synthesis_ignores_objections: float = 0
    composite: float = 0


class RunEvaluation(BaseModel):
    task_success: float = 0
    groundedness: float = 0
    objection_coverage: float = 0
    unsupported_assertion_rate: float = 0
    redundancy_rate: float = 0
    novelty_usefulness: float = 0
    requirement_fidelity: float = 0
    verification_quality: float = 0
    regression_vs_prior_champion: float = 0
    slop: SlopMetrics = Field(default_factory=SlopMetrics)
    overall_score: float = 0
    accepted: bool = False
    notes: list[str] = Field(default_factory=list)


# ── Run manifest ─────────────────────────────────────────────────────

class RunManifest(BaseModel):
    run_id: str = Field(default_factory=lambda: f"run_{uuid4().hex[:12]}")
    contract_id: str
    domain: TaskDomain
    adapter_name: str = "generic"
    policy_id: str = "champion_default"
    status: RunStatus = RunStatus.RUNNING
    started_at: datetime
    ended_at: datetime | None = None
    decision: AdvanceAction | None = None
    summary: str = ""
    artifact_paths: dict[str, str] = Field(default_factory=dict)


# ── Policy ───────────────────────────────────────────────────────────

class PolicySnapshot(BaseModel):
    policy_id: str = Field(default_factory=lambda: f"policy_{uuid4().hex[:8]}")
    version: int = 1
    parent_id: str | None = None
    surfaces: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    benchmark_summary: dict[str, float] = Field(default_factory=dict)
    is_champion: bool = False
    generation: str = "initial"


# ── Benchmark ────────────────────────────────────────────────────────

class BenchmarkExpectation(BaseModel):
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    min_groundedness: float = 0.3
    max_slop: float = 0.6
    min_requirement_fidelity: float = 0.4


class BenchmarkCase(BaseModel):
    case_id: str
    is_canary: bool = False
    submission: TaskSubmission
    expectation: BenchmarkExpectation
