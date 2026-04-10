"""Pre-mortem failure router: cheap early signals predict likely bad runs.

Extracts features from contract, evidence, and dialectic artifacts (available
before expensive execution) and produces a risk score.  The autopilot loop or
runner can use this score to route high-risk runs into more scrutiny or skip
execution entirely, saving compute on runs that are very likely to fail.

This module is EXPERIMENTAL.  All routing behaviour is opt-in via explicit
flags; default pipeline behaviour is unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Feature extraction ───────────────────────────────────────────────


@dataclass
class PreMortemFeatures:
    """Cheap features available after compile + explore + plan, before execution."""

    # Evidence signals
    evidence_item_count: int = 0
    evidence_gap_count: int = 0
    evidence_gap_ratio: float = 0.0  # gaps / total coverage keys
    coverage_density: float = 0.0  # fraction of coverage keys with >=1 item

    # Dialectic signals
    objection_count: int = 0
    max_objection_severity: float = 0.0
    mean_objection_severity: float = 0.0
    unresolved_question_count: int = 0
    synthesis_step_count: int = 0

    # Contract complexity signals
    acceptance_criteria_count: int = 0
    deliverable_count: int = 0
    constraint_count: int = 0
    contract_complexity: int = 0  # sum of above three

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_features(
    contract: Any,
    evidence: Any,
    dialectic: Any,
) -> PreMortemFeatures:
    """Extract pre-mortem features from pipeline artifacts.

    Accepts either Pydantic models or plain dicts (for working with stored
    JSON artifacts).
    """
    f = PreMortemFeatures()

    # --- Evidence ---
    if isinstance(evidence, dict):
        items = evidence.get("items", [])
        gaps = evidence.get("gaps", [])
        cov_map = evidence.get("coverage_map", {})
    else:
        items = getattr(evidence, "items", [])
        gaps = getattr(evidence, "gaps", [])
        cov_map = getattr(evidence, "coverage_map", {})

    f.evidence_item_count = len(items)
    f.evidence_gap_count = len(gaps)
    total_keys = len(cov_map) if cov_map else 0
    if total_keys > 0:
        filled = sum(1 for v in cov_map.values() if v)
        f.coverage_density = filled / total_keys
        f.evidence_gap_ratio = len(gaps) / total_keys
    else:
        f.evidence_gap_ratio = 1.0 if gaps else 0.0

    # --- Dialectic ---
    if isinstance(dialectic, dict):
        objections = dialectic.get("objection_ledger", [])
        unresolved = dialectic.get("unresolved_questions", [])
        synth_steps = dialectic.get("synthesis_steps", [])
    else:
        objections = getattr(dialectic, "objection_ledger", [])
        unresolved = getattr(dialectic, "unresolved_questions", [])
        synth_steps = getattr(dialectic, "synthesis_steps", [])

    f.objection_count = len(objections)
    if objections:
        sevs = []
        for obj in objections:
            sev = obj.get("severity", 0.5) if isinstance(obj, dict) else getattr(obj, "severity", 0.5)
            sevs.append(sev)
        f.max_objection_severity = max(sevs)
        f.mean_objection_severity = sum(sevs) / len(sevs)
    f.unresolved_question_count = len(unresolved)
    f.synthesis_step_count = len(synth_steps)

    # --- Contract complexity ---
    if isinstance(contract, dict):
        criteria = contract.get("acceptance_criteria", [])
        deliverables = contract.get("deliverables", [])
        constraints = contract.get("constraints", [])
    else:
        criteria = getattr(contract, "acceptance_criteria", [])
        deliverables = getattr(contract, "deliverables", [])
        constraints = getattr(contract, "constraints", [])

    f.acceptance_criteria_count = len(criteria)
    f.deliverable_count = len(deliverables)
    f.constraint_count = len(constraints)
    f.contract_complexity = len(criteria) + len(deliverables) + len(constraints)

    return f


# ── Risk scoring ─────────────────────────────────────────────────────

# Default weights derived from empirical observation on 27 runs:
# - evidence_poverty (items=0, many gaps) is the strongest single predictor
# - unresolved questions amplify the signal
# - high max objection severity alone is NOT sufficient (some high-sev runs succeed)
_DEFAULT_WEIGHTS: dict[str, float] = {
    "evidence_poverty": 0.40,
    "gap_ratio": 0.20,
    "unresolved_density": 0.25,
    "objection_severity": 0.15,
}

# Thresholds
RISK_THRESHOLD_SCRUTINIZE = 0.50
RISK_THRESHOLD_SKIP = 0.80


@dataclass
class PreMortemScore:
    """Risk assessment produced before execution."""

    risk_score: float = 0.0
    routing: str = "normal"  # "normal" | "scrutinize" | "skip"
    evidence_poverty_signal: float = 0.0
    gap_ratio_signal: float = 0.0
    unresolved_density_signal: float = 0.0
    objection_severity_signal: float = 0.0
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_risk(
    features: PreMortemFeatures,
    *,
    weights: dict[str, float] | None = None,
    threshold_scrutinize: float = RISK_THRESHOLD_SCRUTINIZE,
    threshold_skip: float = RISK_THRESHOLD_SKIP,
) -> PreMortemScore:
    """Compute a risk score from pre-mortem features.

    Returns a PreMortemScore with routing recommendation.
    """
    w = weights or _DEFAULT_WEIGHTS
    result = PreMortemScore()

    # Signal 1: evidence poverty — no items is the strongest predictor
    if features.evidence_item_count == 0 and features.evidence_gap_count > 0:
        result.evidence_poverty_signal = 1.0
    elif features.evidence_item_count == 0:
        result.evidence_poverty_signal = 0.5
    else:
        # Scale down as items increase relative to gaps
        ratio = features.evidence_item_count / max(features.evidence_gap_count, 1)
        result.evidence_poverty_signal = max(0.0, 1.0 - ratio)

    # Signal 2: gap ratio — fraction of coverage keys that are gaps
    result.gap_ratio_signal = min(1.0, features.evidence_gap_ratio)

    # Signal 3: unresolved question density — unresolved / contract_complexity
    if features.contract_complexity > 0:
        result.unresolved_density_signal = min(
            1.0,
            features.unresolved_question_count / features.contract_complexity,
        )
    elif features.unresolved_question_count > 0:
        result.unresolved_density_signal = 1.0

    # Signal 4: max objection severity
    result.objection_severity_signal = features.max_objection_severity

    # Weighted combination
    result.risk_score = (
        w.get("evidence_poverty", 0.40) * result.evidence_poverty_signal
        + w.get("gap_ratio", 0.20) * result.gap_ratio_signal
        + w.get("unresolved_density", 0.25) * result.unresolved_density_signal
        + w.get("objection_severity", 0.15) * result.objection_severity_signal
    )
    result.risk_score = min(1.0, max(0.0, result.risk_score))

    # Routing decision
    if result.risk_score >= threshold_skip:
        result.routing = "skip"
    elif result.risk_score >= threshold_scrutinize:
        result.routing = "scrutinize"
    else:
        result.routing = "normal"

    # Rationale
    parts = []
    if result.evidence_poverty_signal > 0.5:
        parts.append(
            f"evidence poverty ({features.evidence_item_count} items, "
            f"{features.evidence_gap_count} gaps)"
        )
    if result.unresolved_density_signal > 0.5:
        parts.append(
            f"high unresolved density ({features.unresolved_question_count} "
            f"unresolved / {features.contract_complexity} complexity)"
        )
    if result.objection_severity_signal > 0.8:
        parts.append(
            f"high objection severity ({features.max_objection_severity:.2f})"
        )
    if parts:
        result.rationale = f"Risk {result.risk_score:.2f} ({result.routing}): {'; '.join(parts)}"
    else:
        result.rationale = f"Risk {result.risk_score:.2f} ({result.routing}): no strong warning signals"

    return result


# ── Retrospective validation ─────────────────────────────────────────


def validate_prediction(
    score: PreMortemScore,
    evaluation: Any,
) -> dict[str, Any]:
    """Compare a pre-mortem prediction against actual run outcome.

    Returns a dict with prediction accuracy metrics, useful for tuning
    weights and thresholds.
    """
    if isinstance(evaluation, dict):
        task_success = evaluation.get("task_success", 0.0)
        overall_score = evaluation.get("overall_score", 0.0)
        accepted = evaluation.get("accepted", False)
    else:
        task_success = getattr(evaluation, "task_success", 0.0)
        overall_score = getattr(evaluation, "overall_score", 0.0)
        accepted = getattr(evaluation, "accepted", False)

    # A "bad" run is one that failed or scored poorly
    actual_bad = task_success < 0.5 or overall_score < 0.5 or not accepted
    predicted_bad = score.routing in ("scrutinize", "skip")

    return {
        "risk_score": score.risk_score,
        "routing": score.routing,
        "task_success": task_success,
        "overall_score": overall_score,
        "accepted": accepted,
        "actual_bad": actual_bad,
        "predicted_bad": predicted_bad,
        "true_positive": predicted_bad and actual_bad,
        "false_positive": predicted_bad and not actual_bad,
        "true_negative": not predicted_bad and not actual_bad,
        "false_negative": not predicted_bad and actual_bad,
    }
