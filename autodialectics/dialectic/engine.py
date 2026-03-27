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

# ── Antithesis parsing regexes ─────────────────────────────────────────
# These must handle multiple Claude output styles:
#   Style A: "### 1) Claim being challenged: <text>"
#   Style B: "**Claim challenged:** <text>"
#   Style C: "### Objection 1: <title>\n**Claim challenged:** <text>"
#   Style D: "| 1 | <claim> | <objection> | <severity> |" (table)

_CLAIM_LINE_RE = re.compile(
    r"^(?:#+\s*)?(?:\d+[.)]\s*)?(?:\*\*)?(?:claim(?:\s+(?:being\s+)?challenged)?|objection\s+to)(?:\*\*)?\s*:?\s*(.+)$",
    re.IGNORECASE,
)
# Only match headers like "### Objection 1: <title>" — requires a leading # or number
_OBJECTION_HEADER_RE = re.compile(
    r"^(?:#+\s+)(?:\*\*)?objection\s*\d*(?:\*\*)?\s*:\s*(.+)$",
    re.IGNORECASE,
)
_OBJECTION_LINE_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?objection(?:\*\*)?\s*:?\s*(.*)$",
    re.IGNORECASE,
)
_SEVERITY_LINE_RE = re.compile(
    r"^(?:#+\s*)?(?:\*\*)?severity\s*(?:\*\*)?\s*:?\s*(?:\*\*)?([0-9.]+)",
    re.IGNORECASE,
)
# Table row: | # | claim | objection | severity |
_TABLE_ROW_RE = re.compile(
    r"^\|\s*\d+\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*\**([0-9.]+)\**\s*\|",
    re.MULTILINE,
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
            "You are a rigorous critical reviewer. Your job is to find real flaws, "
            "risks, and gaps in the proposed plan. Be adversarial but constructive. "
            "Do not invent problems that don't exist — focus on genuine weaknesses."
        )
        user = (
            f"Task: {contract.title}\n\n"
            f"Proposed plan:\n{thesis_text}\n\n"
            f"Evidence summary: {evidence.summary}\n\n"
            f"Instructions: {prompt_template}\n\n"
            f"You MUST format each objection using EXACTLY this structure "
            f"(one block per objection):\n\n"
            f"Claim being challenged: <the specific claim or step you are objecting to>\n"
            f"Objection: <your specific, concrete objection>\n"
            f"Severity: <float between 0.0 and 1.0>\n\n"
            f"Separate each objection block with a blank line. "
            f"Do not use markdown headers, bold, or tables for the Claim/Objection/Severity lines. "
            f"You may add commentary before the first objection and after the last one."
        )
        resp = self.model_client.complete(  # type: ignore[union-attr]
            role="critic", system_prompt=system, user_prompt=user
        )
        summary = resp.content
        objections = _parse_antithesis(summary)
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
            "critical objections to produce an improved plan. You MUST "
            "address every objection explicitly — state whether you accept "
            "or reject each one and how the revised plan incorporates it."
        )
        obj_text = "\n".join(
            f"- [Severity {o.severity:.1f}] {o.claim}: {o.objection}"
            for o in objections
        )
        objections_block = obj_text or antithesis_text
        user = (
            f"Task: {contract.title}\n\n"
            f"Original plan:\n{thesis_text}\n\n"
            f"Objections:\n{objections_block}\n\n"
            f"Instructions: {prompt_template}\n\n"
            f"For each objection above, state whether you ACCEPT (incorporate "
            f"it into the plan) or REJECT (explain why it doesn't apply). "
            f"Then output the revised step-by-step plan."
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

        # ── Mark objection dispositions based on synthesis text ──
        _resolve_objection_dispositions(objections, synthesis_text)

        unresolved = [
            o.objection for o in objections
            if o.severity > 0.8 and o.accepted is not True
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


# ── Module-level helpers ─────────────────────────────────────────────


def _parse_antithesis(text: str) -> list[ObjectionRecord]:
    """Parse structured objections from antithesis text.

    Handles multiple output formats:
    1. Line-based: "Claim being challenged: ...\\nObjection: ...\\nSeverity: ..."
    2. Markdown headers: "### Objection N: ...\\n**Claim challenged:** ..."
    3. Table rows: "| # | claim | objection | severity |"
    """
    objections: list[ObjectionRecord] = []

    # ── Try table parsing first ──
    for table_match in _TABLE_ROW_RE.finditer(text):
        claim = table_match.group(1).strip().strip("*")
        objection = table_match.group(2).strip().strip("*")
        try:
            severity = float(table_match.group(3).rstrip("."))
        except ValueError:
            severity = 0.5
        if claim and objection:
            objections.append(ObjectionRecord(
                claim=claim, objection=objection, severity=severity,
            ))
    if objections:
        return objections

    # ── Line-based parsing (primary path) ──
    current_claim = ""
    current_objection = ""
    current_severity = 0.5
    collecting_objection = False
    pending_header_title = ""

    def flush() -> None:
        nonlocal current_claim, current_objection, current_severity
        nonlocal collecting_objection, pending_header_title
        if current_claim and current_objection:
            objections.append(ObjectionRecord(
                claim=current_claim.strip(),
                objection=current_objection.strip(),
                severity=current_severity,
            ))
        current_claim = ""
        current_objection = ""
        current_severity = 0.5
        collecting_objection = False
        pending_header_title = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue

        # Check for "### Objection N: <title>" header style
        header_match = _OBJECTION_HEADER_RE.match(line)
        if header_match:
            flush()
            pending_header_title = header_match.group(1).strip().rstrip("*").strip()
            continue

        # Check for claim line
        claim_match = _CLAIM_LINE_RE.match(line)
        if claim_match:
            if current_claim:
                flush()
            current_claim = claim_match.group(1).strip().rstrip("*").strip()
            collecting_objection = False
            continue

        # Check for objection line
        objection_match = _OBJECTION_LINE_RE.match(line)
        if objection_match:
            claim_context = current_claim or pending_header_title
            if claim_context:
                if not current_claim:
                    current_claim = claim_context
                objection_text = objection_match.group(1).strip()
                current_objection = objection_text
                collecting_objection = True
                continue

        # Check for severity
        severity_match = _SEVERITY_LINE_RE.match(line)
        if severity_match and (current_claim or pending_header_title):
            if not current_claim and pending_header_title:
                current_claim = pending_header_title
            try:
                current_severity = float(severity_match.group(1).rstrip("."))
            except ValueError:
                pass
            continue

        # Continuation lines for objection body
        if collecting_objection and current_claim:
            clean_line = line.strip("* ")
            if clean_line:
                current_objection = f"{current_objection} {clean_line}".strip()

    flush()
    return objections


def _resolve_objection_dispositions(
    objections: list[ObjectionRecord],
    synthesis_text: str,
) -> None:
    """Set accepted/disposition on each objection by checking if the synthesis addressed it.

    Uses keyword overlap between each objection's claim+objection text and the
    synthesis. Also looks for explicit accept/reject language near objection keywords.
    """
    from autodialectics.utils.text import keyword_set

    synthesis_lower = synthesis_text.lower()
    synthesis_kw = keyword_set(synthesis_text)

    for obj in objections:
        obj_kw = keyword_set(f"{obj.claim} {obj.objection}")
        if not obj_kw:
            continue

        overlap = len(obj_kw & synthesis_kw) / len(obj_kw)

        # Extract a few distinctive words from the claim for context matching
        claim_words = [w for w in obj.claim.lower().split() if len(w) > 4][:3]
        context_found = any(w in synthesis_lower for w in claim_words)

        if overlap > 0.3 and context_found:
            obj.accepted = True
            obj.disposition = "addressed"
        elif overlap > 0.15:
            obj.accepted = True
            obj.disposition = "partially addressed"
        else:
            obj.accepted = False
            obj.disposition = "not addressed in synthesis"


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
