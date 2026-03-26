"""Dialectical planning: thesis → antithesis → synthesis with LLM or heuristic fallback."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from autodialectics.routing.cliproxy import is_request_failure_response_text
from autodialectics.schemas import (
    AdvanceAction,
    DialecticArtifact,
    ObjectionRecord,
    VerificationVerdict,
)

if TYPE_CHECKING:
    from autodialectics.routing.cliproxy import ModelClient
    from autodialectics.schemas import EvidenceBundle, TaskContract

logger = logging.getLogger(__name__)

_CLAIM_LINE_RE = re.compile(
    r"^(?:#+\s*)?(?:\d+[.)]\s*)?(?:claim(?: being challenged)?|objection to)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_OBJECTION_LINE_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?objection(?:\*\*)?\s*:?\s*(.*)$",
    re.IGNORECASE,
)
_SEVERITY_LINE_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?severity(?:\*\*)?\s*:\s*([0-9.]+)",
    re.IGNORECASE,
)


@dataclass
class AdvanceDecision:
    """Decision from the advance gate: accept, reject, revise, or rollback."""

    action: AdvanceAction
    rationale: str
    confidence: float = 0.0


class DialecticalPlanner:
    """Generate a dialectic plan (thesis/antithesis/synthesis) for a task."""

    def __init__(self, model_client: ModelClient | None = None) -> None:
        self.model_client = model_client

    # ── Public API ────────────────────────────────────────────────────

    def plan(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        policy_surfaces: dict[str, str] | None = None,
    ) -> DialecticArtifact:
        """Run thesis → antithesis → synthesis pipeline."""
        surfaces = policy_surfaces or {}

        thesis_prompt = surfaces.get(
            "thesis",
            "Create a step-by-step plan to accomplish the task objectives.",
        )
        antithesis_prompt = surfaces.get(
            "antithesis",
            "Identify flaws, gaps, and risks in the proposed plan.",
        )
        synthesis_prompt = surfaces.get(
            "synthesis",
            "Reconcile the thesis and antithesis into an improved plan.",
        )

        if self.model_client and not self.model_client.offline:
            thesis = self._llm_thesis(contract, evidence, thesis_prompt)
            if is_request_failure_response_text(thesis[0]):
                logger.warning(
                    "Planner thesis request failed; falling back to heuristic plan"
                )
                artifact = self._heuristic_plan(contract, evidence)
            else:
                antithesis = self._llm_antithesis(
                    contract, evidence, thesis, antithesis_prompt
                )
                if is_request_failure_response_text(antithesis[0]):
                    logger.warning(
                        "Planner antithesis request failed; falling back to heuristic plan"
                    )
                    artifact = self._heuristic_plan(contract, evidence)
                else:
                    artifact = self._llm_synthesis(
                        contract, evidence, thesis, antithesis, synthesis_prompt
                    )
                    if is_request_failure_response_text(artifact.synthesis):
                        logger.warning(
                            "Planner synthesis request failed; falling back to heuristic plan"
                        )
                        artifact = self._heuristic_plan(contract, evidence)
        else:
            artifact = self._heuristic_plan(contract, evidence)

        logger.info(
            "Dialectical plan complete: %d synthesis steps, %d objections",
            len(artifact.synthesis_steps),
            len(artifact.objection_ledger),
        )
        return artifact

    # ── LLM-backed planning ───────────────────────────────────────────

    def _llm_thesis(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        prompt_template: str,
    ) -> tuple[str, list[str]]:
        """Generate thesis via LLM. Returns (thesis_text, steps)."""
        system = "You are a task planning assistant. Generate a clear, structured plan."
        user = (
            f"Task: {contract.title}\n\n"
            f"Objectives:\n"
            + "\n".join(f"- {o}" for o in contract.objectives)
            + f"\n\nConstraints:\n"
            + "\n".join(f"- {c}" for c in contract.constraints)
            + f"\n\nEvidence summary: {evidence.summary}\n\n"
            f"Instructions: {prompt_template}\n\n"
            f"Output a numbered step-by-step plan."
        )
        resp = self.model_client.complete(  # type: ignore[union-attr]
            role="planner", system_prompt=system, user_prompt=user
        )
        thesis_text = resp.content
        steps = [
            line.strip().lstrip("0123456789.)- ")
            for line in thesis_text.splitlines()
            if line.strip() and line.strip()[0].isdigit()
        ]
        return thesis_text, steps

    def _llm_antithesis(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        thesis: tuple[str, list[str]],
        prompt_template: str,
    ) -> tuple[str, list[ObjectionRecord]]:
        """Generate antithesis via LLM. Returns (summary, objections)."""
        thesis_text, thesis_steps = thesis
        system = (
            "You are a critical reviewer. Identify flaws, risks, and gaps "
            "in the proposed plan. Be specific and constructive."
        )
        user = (
            f"Task: {contract.title}\n\n"
            f"Proposed plan:\n{thesis_text}\n\n"
            f"Evidence summary: {evidence.summary}\n\n"
            f"Instructions: {prompt_template}\n\n"
            f"For each objection, state the claim being challenged and "
            f"your specific objection. Rate severity 0-1."
        )
        resp = self.model_client.complete(  # type: ignore[union-attr]
            role="critic", system_prompt=system, user_prompt=user
        )
        summary = resp.content

        objections: list[ObjectionRecord] = []
        current_claim = ""
        current_objection = ""
        current_severity = 0.5
        collecting_objection = False

        def flush_current() -> None:
            nonlocal current_claim, current_objection, current_severity, collecting_objection
            if current_claim and current_objection:
                objections.append(
                    ObjectionRecord(
                        claim=current_claim.strip(),
                        objection=current_objection.strip(),
                        severity=current_severity,
                    )
                )
            current_claim = ""
            current_objection = ""
            current_severity = 0.5
            collecting_objection = False

        for raw_line in summary.splitlines():
            line = raw_line.strip()
            if not line or line == "---":
                continue

            claim_match = _CLAIM_LINE_RE.match(line)
            if claim_match:
                flush_current()
                current_claim = claim_match.group(1).strip()
                continue

            objection_match = _OBJECTION_LINE_RE.match(line)
            if objection_match and current_claim:
                objection_text = objection_match.group(1).strip()
                current_objection = objection_text
                collecting_objection = True
                continue

            severity_match = _SEVERITY_LINE_RE.match(line)
            if severity_match and current_claim:
                try:
                    current_severity = float(severity_match.group(1).rstrip("."))
                except ValueError:
                    pass
                continue

            if collecting_objection and current_claim:
                clean_line = line.strip("* ")
                if clean_line:
                    current_objection = f"{current_objection} {clean_line}".strip()

        flush_current()

        return summary, objections

    def _llm_synthesis(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        thesis: tuple[str, list[str]],
        antithesis: tuple[str, list[ObjectionRecord]],
        prompt_template: str,
    ) -> DialecticArtifact:
        """Generate synthesis via LLM, reconciling thesis and antithesis."""
        thesis_text, thesis_steps = thesis
        antithesis_text, objections = antithesis

        system = (
            "You are a synthesis engine. Reconcile a proposed plan with "
            "critical objections to produce an improved plan. Address each "
            "objection explicitly."
        )
        obj_text = "\n".join(
            f"- [{o.severity:.1f}] {o.claim}: {o.objection}" for o in objections
        )
        objections_block = obj_text or antithesis_text
        user = (
            f"Task: {contract.title}\n\n"
            f"Original plan:\n{thesis_text}\n\n"
            f"Objections:\n{objections_block}\n\n"
            f"Instructions: {prompt_template}\n\n"
            f"Output a revised step-by-step plan that addresses all objections."
        )
        resp = self.model_client.complete(  # type: ignore[union-attr]
            role="synthesist", system_prompt=system, user_prompt=user
        )
        synthesis_text = resp.content
        steps = [
            line.strip().lstrip("0123456789.)- ")
            for line in synthesis_text.splitlines()
            if line.strip() and line.strip()[0].isdigit()
        ]

        unresolved = [
            o.objection for o in objections if o.severity > 0.8
        ]
        assumptions = [
            o.claim for o in objections if o.severity <= 0.3
        ]

        return DialecticArtifact(
            thesis=thesis_text,
            thesis_steps=thesis_steps,
            antithesis_summary=antithesis_text,
            synthesis=synthesis_text,
            synthesis_steps=steps,
            objection_ledger=objections,
            unresolved_questions=unresolved,
            assumptions=assumptions,
        )

    # ── Heuristic (offline) fallback ──────────────────────────────────

    def _heuristic_plan(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
    ) -> DialecticArtifact:
        """Generate a basic dialectic plan without LLM calls."""
        thesis_steps: list[str] = []
        for i, obj in enumerate(contract.objectives, 1):
            thesis_steps.append(f"Address objective: {obj}")

        for d in contract.deliverables:
            thesis_steps.append(f"Produce deliverable: {d}")

        thesis = (
            "Plan (heuristic):\n"
            + "\n".join(f"{i+1}. {s}" for i, s in enumerate(thesis_steps))
        )

        # Generate objections from constraints
        objections: list[ObjectionRecord] = []
        for c in contract.constraints:
            objections.append(
                ObjectionRecord(
                    claim="Proposed plan proceeds without considering constraints",
                    objection=f"Constraint: {c}",
                    severity=0.5,
                )
            )

        if evidence.gaps:
            objections.append(
                ObjectionRecord(
                    claim="Evidence base is sufficient for planning",
                    objection=f"Evidence gaps: {', '.join(evidence.gaps)}",
                    severity=0.7,
                )
            )

        antithesis_summary = (
            "Heuristic antithesis: "
            + "; ".join(o.objection for o in objections)
        )

        synthesis_steps = list(thesis_steps)
        synthesis_steps.insert(0, "Review and validate all constraints")
        if evidence.gaps:
            synthesis_steps.insert(0, "Gather additional evidence for gaps")

        synthesis = (
            "Revised plan (heuristic synthesis):\n"
            + "\n".join(f"{i+1}. {s}" for i, s in enumerate(synthesis_steps))
        )

        return DialecticArtifact(
            thesis=thesis,
            thesis_steps=thesis_steps,
            antithesis_summary=antithesis_summary,
            synthesis=synthesis,
            synthesis_steps=synthesis_steps,
            objection_ledger=objections,
            unresolved_questions=evidence.gaps[:],
            assumptions=[],
        )


# ── Advance Gate ──────────────────────────────────────────────────────


class AdvanceGate:
    """Decide whether to accept, reject, revise, or rollback a run."""

    @staticmethod
    def decide(
        verification: Any,
        evaluation: Any,
        prior_champion_score: float = 0.0,
    ) -> AdvanceDecision:
        """Make an advance decision based on verification and evaluation.

        Parameters
        ----------
        verification : VerificationReport
        evaluation : RunEvaluation
        prior_champion_score : float
            The overall score of the current champion policy.
        """
        verdict = getattr(verification, "verdict", VerificationVerdict.FAIL)
        confidence = getattr(verification, "confidence", 0.0)
        slop = getattr(evaluation, "slop", None)
        overall = getattr(evaluation, "overall_score", 0.0)
        composite_slop = getattr(slop, "composite", 0.0) if slop else 0.0

        # Hard reject: verification failed badly
        if verdict == VerificationVerdict.FAIL and confidence < 0.3:
            return AdvanceDecision(
                action=AdvanceAction.REJECT,
                rationale=(
                    "Verification failed with low confidence. "
                    f"Verdict={verdict.value}, confidence={confidence:.2f}"
                ),
                confidence=confidence,
            )

        # Reject: excessive slop
        if composite_slop > 0.7:
            return AdvanceDecision(
                action=AdvanceAction.REJECT,
                rationale=(
                    f"Excessive slop detected: composite={composite_slop:.2f}"
                ),
                confidence=0.9,
            )

        # Accept: verification passed and score is good
        if (
            verdict == VerificationVerdict.PASS
            and overall >= 0.6
            and composite_slop < 0.4
        ):
            return AdvanceDecision(
                action=AdvanceAction.ACCEPT,
                rationale=(
                    f"Verification passed. Score={overall:.2f}, "
                    f"slop={composite_slop:.2f}"
                ),
                confidence=confidence,
            )

        # Revise: middle ground
        return AdvanceDecision(
            action=AdvanceAction.REVISE,
            rationale=(
                f"Verification verdict={verdict.value}, score={overall:.2f}, "
                f"slop={composite_slop:.2f}. Revision recommended."
            ),
            confidence=confidence * 0.7,
        )
