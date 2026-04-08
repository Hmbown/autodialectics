"""Slop scoring and run evaluation: detect AI slop patterns and evaluate runs."""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autodialectics.schemas import (
    ExecutionArtifact,
    RunEvaluation,
    SlopMetrics,
    TaskContract,
    VerificationCheck,
    VerificationReport,
    VerificationVerdict,
)
from autodialectics.utils.text import (
    keyword_set,
    overlap_score,
    repeated_sentence_ratio,
    trigram_repetition_ratio,
    words,
)

if TYPE_CHECKING:
    from autodialectics.schemas import DialecticArtifact, EvidenceBundle

logger = logging.getLogger(__name__)

_NEGATION_MARKERS = (
    "did not",
    "didn't",
    "does not",
    "doesn't",
    "cannot",
    "can't",
    "unable",
    "without",
    "missing",
    "fail",
    "failed",
    "not ",
    "no ",
)
_SANDBOX_CRITERION_HINTS = (
    "test",
    "tests",
    "pytest",
    "verification",
    "verify",
    "compile",
    "compilation",
)


def _has_unparsed_antithesis_objections(text: str) -> bool:
    """Heuristically detect critique text when no structured objections were parsed."""
    lowered = text.lower()
    if not lowered.strip():
        return False
    return (
        "claim being challenged" in lowered
        or "claim challenged" in lowered
        or "specific objection" in lowered
        or "**objection" in lowered
        or "objection:" in lowered
        or "| severity |" in lowered
        or "## objections" in lowered
        or "severity:" in lowered
        or "severity: 0." in lowered
    )


def _normalize_text(text: str) -> str:
    """Collapse whitespace for resilient phrase matching."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _bounded01(value: float) -> float:
    """Clamp a numeric score into the inclusive [0, 1] range."""
    return max(0.0, min(float(value), 1.0))


def _criterion_sentence_windows(text: str) -> list[str]:
    """Return lightweight sentence-like windows for local negation checks."""
    windows = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [window.strip() for window in windows if window.strip()]


def _has_negated_support(text: str, criterion_keywords: set[str]) -> bool:
    """Return True when the criterion is mentioned only in a negated context."""
    if not text or not criterion_keywords:
        return False

    for window in _criterion_sentence_windows(text):
        window_keywords = keyword_set(window)
        overlap = len(criterion_keywords & window_keywords) / max(len(criterion_keywords), 1)
        if overlap < 0.5:
            continue
        lowered = f" {_normalize_text(window)} "
        if any(marker in lowered for marker in _NEGATION_MARKERS):
            return True
    return False


def _artifact_support_status(
    criterion: str,
    execution: ExecutionArtifact,
    sandbox_command: str | None,
    sandbox_exit_code: int | None,
) -> tuple[str | None, str | None]:
    """Infer criterion status from structured execution artifacts when possible."""
    lowered = criterion.lower()
    sandbox = execution.structured_output.get("sandbox", {})
    no_op_verification = bool(sandbox.get("no_op_verification"))
    no_changes_declared = bool(
        sandbox.get("no_changes_declared")
        or execution.structured_output.get("no_changes_declared")
        or execution.output_text.lstrip().startswith("NO_CHANGES_NEEDED")
    )

    if sandbox_command and any(token in lowered for token in _SANDBOX_CRITERION_HINTS):
        status = "pass" if sandbox_exit_code == 0 else "fail"
        return status, f"Sandbox verification signal: {sandbox_command} (exit={sandbox_exit_code})"

    if no_op_verification and no_changes_declared and sandbox_exit_code == 0:
        if "regression" in lowered or "existing functionality" in lowered:
            return "pass", "No-op sandbox verification passed; existing functionality did not regress."
        if "style" in lowered or "conventions" in lowered:
            return "pass", "No code changes were applied; existing style conventions remain unchanged."

    file_names = [Path(path).name.lower() for path in execution.created_files]
    file_stems = [Path(path).stem.lower() for path in execution.created_files]
    if any(name and name in lowered for name in file_names):
        return "pass", "Created file referenced by criterion."
    if any(stem and stem in lowered for stem in file_stems):
        return "pass", "Created file stem referenced by criterion."

    return None, None


def _writing_criterion_status(
    contract: TaskContract,
    criterion: str,
    execution: ExecutionArtifact,
    evidence: "EvidenceBundle | None",
) -> tuple[str, str] | None:
    """Specialized heuristics for writing-task acceptance criteria."""
    if contract.domain.value != "writing":
        return None

    lowered = criterion.lower()
    output_text = execution.output_text
    output_lower = output_text.lower()
    meta_markers = (
        "revised plan",
        "execution plan",
        "## objectives",
        "## deliverables",
        "## forbidden shortcuts",
        "claim being challenged",
        "objection:",
        "step 1",
    )
    looks_like_finished_prose = not any(marker in output_lower for marker in meta_markers)

    if "tone" in lowered and "style" in lowered:
        if looks_like_finished_prose and len(words(output_text)) >= 40:
            return "pass", "Output reads like a finished revised document."
        if looks_like_finished_prose:
            return "partial", "Output is prose-like but short for a finished revision."
        return "fail", "Output still looks like planning/meta text rather than a revised document."

    if "no factual errors introduced during revision" in lowered:
        if not looks_like_finished_prose:
            return "fail", "Output did not produce a finished revision suitable for factual comparison."
        source_text_parts: list[str] = []
        for asset in contract.relevant_assets:
            if asset.text:
                source_text_parts.append(asset.text)
                continue
            if asset.location:
                path = Path(asset.location)
                if path.is_file():
                    try:
                        source_text_parts.append(path.read_text(encoding="utf-8"))
                    except Exception:
                        pass
        if not source_text_parts and evidence:
            source_text_parts.extend(item.excerpt for item in evidence.items if item.excerpt)
        source_text = "\n".join(source_text_parts)
        source_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", source_text))
        stripped_output = re.sub(r"(?m)^\s*\d+\.\s+", "", output_text)
        output_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", stripped_output))
        new_numbers = output_numbers - source_numbers
        if new_numbers:
            return "fail", f"Revision introduced new numeric claims not present in source: {', '.join(sorted(new_numbers))}"
        return "pass", "Revision did not introduce new numeric factual claims beyond the source material."

    return None


def _research_criterion_status(
    contract: TaskContract,
    criterion: str,
    execution: ExecutionArtifact,
) -> tuple[str, str] | None:
    """Specialized heuristics for research-task acceptance criteria."""
    if contract.domain.value != "research":
        return None

    lowered = criterion.lower()
    output_text = execution.output_text
    output_lower = output_text.lower()

    if "every factual claim cites a verifiable source" in lowered:
        claim_lines = [
            line for line in output_text.splitlines()
            if "[CLAIM]" in line
        ]
        if claim_lines and all("Evidence:" in line for line in claim_lines):
            return "pass", "Each extracted factual claim includes an inline evidence citation."
        if claim_lines:
            return "partial", "Some factual claims were extracted, but citation formatting is inconsistent."
        return "fail", "No explicit factual-claim lines with evidence citations were found."

    if "contradictory evidence is acknowledged and discussed" in lowered:
        contradiction_markers = (
            "contradict",
            "contested",
            "however",
            "by contrast",
            "on the other hand",
            "disputed",
            "mixed evidence",
            "mixed rather than decisive",
            "debate",
            "disagreement",
        )
        if any(marker in output_lower for marker in contradiction_markers):
            return "pass", "Output explicitly acknowledges contested or contradictory evidence."
        return "fail", "No explicit discussion of contradictory or contested evidence was found."

    return None


def _experiment_criterion_status(
    contract: TaskContract,
    criterion: str,
    execution: ExecutionArtifact,
) -> tuple[str, str] | None:
    """Specialized heuristics for experiment-design task acceptance criteria."""
    if contract.domain.value != "experiment":
        return None

    lowered = criterion.lower()
    output_lower = execution.output_text.lower()

    if "experimental procedure is fully specified and reproducible" in lowered:
        section_markers = (
            "hypothesis",
            "variables",
            "procedure",
            "data collection",
            "analysis",
            "expected outcomes",
        )
        reproducibility_markers = (
            "baseline",
            "seed",
            "dataset",
            "config",
            "hardware",
            "version",
            "commit",
            "repeat",
            "orchestration",
            "reproducible",
        )
        section_hits = sum(1 for marker in section_markers if marker in output_lower)
        reproducibility_hits = sum(
            1 for marker in reproducibility_markers if marker in output_lower
        )
        if section_hits >= 4 and reproducibility_hits >= 3:
            return "pass", "Protocol includes the core experiment sections and reproducibility controls."
        if section_hits >= 3 and reproducibility_hits >= 2:
            return "partial", "Protocol structure is mostly complete but reproducibility details are lighter."
        return "fail", "Protocol is missing core reproducibility sections or controls."

    if "confidence intervals or significance tests" in lowered:
        statistical_markers = (
            "confidence interval",
            "confidence intervals",
            "significance test",
            "significance tests",
            "p-value",
            "paired t-test",
            "wilcoxon",
            "mcnemar",
            "anova",
            "bootstrap",
            "fisher's exact test",
        )
        if any(marker in output_lower for marker in statistical_markers):
            return "pass", "Protocol specifies confidence intervals or concrete significance tests."
        return "fail", "No confidence interval or named significance-test plan was found."

    return None


def _analysis_criterion_status(
    contract: TaskContract,
    criterion: str,
    execution: ExecutionArtifact,
) -> tuple[str, str] | None:
    """Specialized heuristics for analysis-task acceptance criteria."""
    if contract.domain.value != "analysis":
        return None

    lowered = criterion.lower()
    output_lower = execution.output_text.lower()

    if "multiple interpretations" in lowered:
        interpretation_markers = (
            "alternative interpretations",
            "multiple interpretations",
            "by contrast",
            "however",
            "on the other hand",
        )
        if any(marker in output_lower for marker in interpretation_markers):
            return "pass", "Output explicitly presents alternative interpretations."
        return "fail", "No explicit alternative-interpretation section or marker was found."

    if "conclusions follow from the evidence presented" in lowered:
        has_conclusions = "## conclusions" in output_lower or "conclusions" in output_lower
        evidence_markers = (
            "evidence",
            "supported",
            "see [",
            "source",
            "confidence:",
        )
        if has_conclusions and any(marker in output_lower for marker in evidence_markers):
            return "pass", "Conclusions are explicitly tied back to cited evidence or support markers."
        return "fail", "Output does not clearly tie conclusions back to evidence."

    return None


def _assess_acceptance_criterion(
    contract: TaskContract,
    criterion: str,
    execution: ExecutionArtifact,
    sandbox_command: str | None,
    sandbox_exit_code: int | None,
    evidence: "EvidenceBundle | None" = None,
) -> tuple[str, str]:
    """Assess one acceptance criterion using overlap, phrase matches, and negation."""
    writing_status = _writing_criterion_status(contract, criterion, execution, evidence)
    if writing_status is not None:
        return writing_status
    research_status = _research_criterion_status(contract, criterion, execution)
    if research_status is not None:
        return research_status
    experiment_status = _experiment_criterion_status(contract, criterion, execution)
    if experiment_status is not None:
        return experiment_status
    analysis_status = _analysis_criterion_status(contract, criterion, execution)
    if analysis_status is not None:
        return analysis_status

    artifact_status, artifact_notes = _artifact_support_status(
        criterion,
        execution,
        sandbox_command,
        sandbox_exit_code,
    )
    if artifact_status is not None:
        return artifact_status, artifact_notes or ""

    text = execution.output_text
    criterion_keywords = keyword_set(criterion)
    text_keywords = keyword_set(text)
    overlap = len(criterion_keywords & text_keywords) / max(len(criterion_keywords), 1)
    phrase_hit = bool(_normalize_text(criterion) and _normalize_text(criterion) in _normalize_text(text))
    negated = _has_negated_support(text, criterion_keywords)

    if negated:
        return "fail", f"Negated criterion mention detected (keyword overlap: {overlap:.2f})"
    if phrase_hit:
        return "pass", "Direct criterion phrase match in execution output."
    if overlap >= 0.45:
        return "pass", f"Strong keyword overlap: {overlap:.2f}"
    if overlap >= 0.20:
        return "partial", f"Partial keyword overlap: {overlap:.2f}"
    return "fail", f"Insufficient keyword overlap: {overlap:.2f}"


class SlopScorer:
    """Compute 12 slop sub-metrics and a weighted composite score."""

    # Weights for composite calculation
    _WEIGHTS: dict[str, float] = {
        "verbosity_without_gain": 0.12,
        "repetition_without_progress": 0.10,
        "unsupported_claims": 0.15,
        "requirement_drift": 0.10,
        "fake_completion": 0.15,
        "self_verification_bias": 0.08,
        "benchmark_gaming": 0.05,
        "shallow_novelty": 0.05,
        "context_contamination": 0.05,
        "refusal_to_surface_uncertainty": 0.05,
        "tool_abuse": 0.05,
        "synthesis_ignores_objections": 0.05,
    }

    def score(
        self,
        *,
        contract: TaskContract,
        execution: ExecutionArtifact,
        dialectic: DialecticArtifact | None = None,
        evidence: EvidenceBundle | None = None,
    ) -> SlopMetrics:
        """Compute all slop sub-metrics and the composite."""
        text = execution.output_text
        summary = execution.summary

        metrics = SlopMetrics()
        metrics.verbosity_without_gain = self._verbosity_without_gain(
            text, summary, contract
        )
        metrics.repetition_without_progress = self._repetition_without_progress(
            text
        )
        metrics.unsupported_claims = self._unsupported_claims(
            text, evidence, execution.declared_uncertainties
        )
        metrics.requirement_drift = self._requirement_drift(
            text, contract
        )
        metrics.fake_completion = self._fake_completion(
            execution, contract
        )
        metrics.self_verification_bias = self._self_verification_bias(
            text, execution.tool_log
        )
        metrics.benchmark_gaming = self._benchmark_gaming(text)
        metrics.shallow_novelty = self._shallow_novelty(text, summary)
        metrics.context_contamination = self._context_contamination(
            text, evidence
        )
        metrics.refusal_to_surface_uncertainty = (
            self._refusal_to_surface_uncertainty(
                text, execution.declared_uncertainties
            )
        )
        metrics.tool_abuse = self._tool_abuse(execution.tool_log)
        metrics.synthesis_ignores_objections = (
            self._synthesis_ignores_objections(
                text, dialectic
            )
        )
        for metric_name in self._WEIGHTS:
            setattr(metrics, metric_name, _bounded01(getattr(metrics, metric_name, 0.0)))

        # Weighted composite
        composite = 0.0
        total_weight = 0.0
        for metric_name, weight in self._WEIGHTS.items():
            value = getattr(metrics, metric_name, 0.0)
            composite += value * weight
            total_weight += weight
        metrics.composite = _bounded01(composite / total_weight if total_weight > 0 else 0.0)

        return metrics

    # ── Sub-metric implementations ────────────────────────────────────

    def _verbosity_without_gain(
        self,
        text: str,
        summary: str,
        contract: TaskContract,
    ) -> float:
        """Penalize long output without proportional information gain."""
        if not text:
            return 0.0
        word_count = len(words(text))
        # Base verbosity penalty for very long outputs
        if word_count < 200:
            return 0.0
        verbosity_ratio = min(word_count / 5000.0, 1.0)
        # Reduce penalty if summary is concise (suggests real content)
        summary_ratio = len(words(summary)) / max(len(words(text)), 1)
        info_density = 1.0 - summary_ratio
        return min(verbosity_ratio * info_density, 1.0)

    def _repetition_without_progress(self, text: str) -> float:
        """Detect repeated sentences and trigrams that add no new info."""
        sent_ratio = repeated_sentence_ratio(text)
        tri_ratio = trigram_repetition_ratio(text)
        return min((sent_ratio + tri_ratio) / 2.0, 1.0)

    def _unsupported_claims(
        self,
        text: str,
        evidence: EvidenceBundle | None,
        uncertainties: list[str],
    ) -> float:
        """Ratio of claim-like statements without evidence support."""
        if not text:
            return 0.0
        # Look for claim patterns
        claim_patterns = [
            r"(?:is|are|was|were) (?:the |a |an )?(?:best|worst|only|first|proven|proves)",
            r"(?:studies show|research shows|it is known|everyone knows)",
            r"(?:clearly|obviously|undoubtedly|certainly)",
            r"(?:we can conclude|it follows that|this means that)",
        ]
        claim_count = 0
        for pattern in claim_patterns:
            claim_count += len(re.findall(pattern, text, re.IGNORECASE))

        if claim_count == 0:
            return 0.0

        # Check how many claims are backed by evidence
        supported = 0
        if evidence and evidence.items:
            for item in evidence.items:
                if item.excerpt and item.excerpt[:100] in text:
                    supported += 1

        uncertainty_ratio = len(uncertainties) / max(claim_count, 1)
        supported = min(supported, claim_count)
        unsupported = max(claim_count - supported, 0)
        return _bounded01(
            unsupported / max(claim_count, 1) * (1.0 - uncertainty_ratio)
        )

    def _requirement_drift(self, text: str, contract: TaskContract) -> float:
        """Detect if output drifts from stated objectives/constraints."""
        if not text:
            return 0.0
        obj_keywords = keyword_set(" ".join(contract.objectives))
        constraint_keywords = keyword_set(" ".join(contract.constraints))
        text_keywords = keyword_set(text)

        weighted_overlap = 0.0
        total_weight = 0.0
        if obj_keywords:
            obj_overlap = len(obj_keywords & text_keywords) / len(obj_keywords)
            weighted_overlap += obj_overlap * 0.6
            total_weight += 0.6
        if constraint_keywords:
            constraint_overlap = (
                len(constraint_keywords & text_keywords)
                / len(constraint_keywords)
            )
            weighted_overlap += constraint_overlap * 0.4
            total_weight += 0.4
        if total_weight == 0.0:
            return 0.0

        drift = 1.0 - (weighted_overlap / total_weight)
        return max(0.0, min(drift, 1.0))

    def _fake_completion(
        self,
        execution: ExecutionArtifact,
        contract: TaskContract,
    ) -> float:
        """Detect fake completion (claiming done without evidence)."""
        indicators = 0
        total = 0

        # Check if all deliverables are claimed but no test results or files
        has_output = bool(execution.output_text.strip())
        has_files = bool(execution.created_files)
        has_tests = bool(execution.test_results)
        has_patches = bool(execution.patches)

        if has_output:
            total += 1
            completion_claims = re.findall(
                r"(?:done|complete|finished|implemented|resolved)\b",
                execution.output_text,
                re.IGNORECASE,
            )
            if completion_claims and not (has_files or has_tests or has_patches):
                indicators += 1

        # Check if claimed uncertainties are empty when constraints exist
        if contract.constraints and not execution.declared_uncertainties:
            total += 1
            indicators += 1  # Suspicious: complex task with no uncertainties

        # Check if status says completed but no artifacts
        if execution.status == "completed" and not (has_files or has_tests):
            total += 1
            if not has_output or len(execution.output_text) < 50:
                indicators += 1

        return indicators / total if total > 0 else 0.0

    def _self_verification_bias(
        self, text: str, tool_log: list[str]
    ) -> float:
        """Detect patterns of self-verifying without independent checks."""
        if not text:
            return 0.0
        self_verify_patterns = [
            r"(?:i (?:can |have )?verif|verification (?:shows|confirms|proves))",
            r"(?:tests? (?:pass|passed|all green))",
            r"(?:correct|right|working) as (?:expected|intended)",
        ]
        matches = sum(
            len(re.findall(p, text, re.IGNORECASE))
            for p in self_verify_patterns
        )
        independent_checks = sum(
            1 for entry in tool_log
            if "verify" in entry.lower() or "test" in entry.lower()
        )
        if matches == 0:
            return 0.0
        bias = max(matches - independent_checks, 0) / max(matches, 1)
        return min(bias, 1.0)

    def _benchmark_gaming(self, text: str) -> float:
        """Detect patterns suggesting benchmark gaming."""
        if not text:
            return 0.0
        gaming_patterns = [
            r"(?:optimized (?:specifically|just) (?:for|to pass))",
            r"(?:hardcoded|hard-coded)",
            r"(?:cheat|gaming|gaming the)",
            r"(?:overfit|over-fit)",
            r"(?:train(?:ing|ed) (?:on|with) (?:the )?(?:benchmark|test))",
        ]
        matches = sum(
            len(re.findall(p, text, re.IGNORECASE))
            for p in gaming_patterns
        )
        return min(matches * 0.3, 1.0)

    def _shallow_novelty(self, text: str, summary: str) -> float:
        """Detect novelty claims that are superficial."""
        if not text:
            return 0.0
        novelty_claims = len(
            re.findall(
                r"\b(?:novel|innovative|breakthrough|revolutionary|unique)\b",
                text,
                re.IGNORECASE,
            )
        )
        if novelty_claims == 0:
            return 0.0
        # Check if summary backs up novelty claims
        summary_novelty = len(
            re.findall(
                r"\b(?:novel|innovative|breakthrough|revolutionary|unique)\b",
                summary,
                re.IGNORECASE,
            )
        )
        # If novelty claimed in text but not in summary, might be shallow
        shallow = max(novelty_claims - summary_novelty, 0)
        return min(shallow / max(novelty_claims, 1), 1.0)

    def _context_contamination(
        self,
        text: str,
        evidence: EvidenceBundle | None,
    ) -> float:
        """Detect contamination from context/prompt leaking into output."""
        if not text or not evidence:
            return 0.0
        total_overlap = 0.0
        checks = 0
        for item in evidence.items:
            if item.excerpt:
                score = overlap_score(text, item.excerpt)
                total_overlap += score
                checks += 1
        avg_overlap = total_overlap / checks if checks > 0 else 0.0
        # Very high overlap suggests verbatim copying rather than synthesis
        return min(max(avg_overlap - 0.3, 0.0) / 0.5, 1.0)

    def _refusal_to_surface_uncertainty(
        self, text: str, uncertainties: list[str]
    ) -> float:
        """Penalize failure to acknowledge uncertainty."""
        if not text:
            return 0.0
        # Look for hedging language (good) vs. confident assertions (bad)
        hedge_patterns = [
            r"\b(?:uncertain|unclear|unknown|ambiguous|tentative)\b",
            r"\b(?:may|might|could|possibly|potentially)\b",
            r"\b(?:further (?:investigation|research|analysis) (?:is )?(?:needed|required))\b",
        ]
        hedges = sum(
            len(re.findall(p, text, re.IGNORECASE))
            for p in hedge_patterns
        )
        confident_assertions = len(
            re.findall(
                r"\b(?:definitely|certainly|absolutely|guaranteed|unquestionably)\b",
                text,
                re.IGNORECASE,
            )
        )
        if confident_assertions == 0 and len(uncertainties) == 0:
            return 0.0
        # Low hedging + high confidence + no declared uncertainties = bad
        refusal_score = 1.0 - (hedges / max(confident_assertions + hedges, 1))
        if uncertainties:
            refusal_score *= 0.3  # Declared uncertainties reduce penalty
        return min(refusal_score, 1.0)

    def _tool_abuse(self, tool_log: list[str]) -> float:
        """Detect unnecessary or excessive tool use."""
        if not tool_log:
            return 0.0
        redundant = sum(
            1 for entry in tool_log
            if "redundant" in entry.lower() or "duplicate" in entry.lower()
        )
        return min(redundant / max(len(tool_log), 1), 1.0)

    def _synthesis_ignores_objections(
        self,
        text: str,
        dialectic: DialecticArtifact | None,
    ) -> float:
        """Detect if synthesis ignored serious objections."""
        if not dialectic or not dialectic.objection_ledger:
            return 0.0
        serious = [
            o for o in dialectic.objection_ledger if o.severity > 0.5
        ]
        if not serious:
            return 0.0
        addressed = 0
        for obj in serious:
            # Check if any key terms from the objection appear in the text
            obj_keywords = keyword_set(obj.objection)
            if obj_keywords and obj_keywords & keyword_set(text):
                addressed += 1
        ignored = len(serious) - addressed
        return min(ignored / len(serious), 1.0)


class RunEvaluator:
    """Independent verification and composite evaluation of runs."""

    def __init__(self) -> None:
        self.slop_scorer = SlopScorer()

    # ── Verification ──────────────────────────────────────────────────

    def verify(
        self,
        contract: TaskContract,
        execution: ExecutionArtifact,
        *,
        evidence: EvidenceBundle | None = None,
    ) -> VerificationReport:
        """Independent verification against acceptance criteria."""
        checks: list[VerificationCheck] = []
        unmet: list[str] = []
        cited_evidence: list[str] = []

        text = execution.output_text
        sandbox = execution.structured_output.get("sandbox", {})
        sandbox_command = sandbox.get("test_command")
        sandbox_exit_code = sandbox.get("test_exit_code")
        if execution.status != "completed":
            notes = "Execution did not complete successfully."
            if execution.structured_output.get("llm_request_failed"):
                notes = "Execution failed because the configured LLM endpoint request failed."
            elif execution.structured_output.get("offline_mode"):
                notes = "Execution failed because the runtime was in offline mode."
            elif sandbox.get("protocol_violation"):
                notes = "Execution failed because the executor did not return FILE blocks or NO_CHANGES_NEEDED."
            unmet.append("Execution completed successfully")
            checks.append(
                VerificationCheck(
                    criterion="Execution completed successfully",
                    status="fail",
                    notes=notes,
                )
            )

        if contract.domain.value == "code" and sandbox_command:
            sandbox_status = "pass" if sandbox_exit_code == 0 else "fail"
            if sandbox_status == "fail":
                unmet.append("Sandbox verification tests pass")
            checks.append(
                VerificationCheck(
                    criterion="Sandbox verification tests pass",
                    status=sandbox_status,
                    notes=f"{sandbox_command} (exit={sandbox_exit_code})",
                )
            )

        for criterion in contract.acceptance_criteria:
            status, notes = _assess_acceptance_criterion(
                contract,
                criterion,
                execution,
                sandbox_command,
                sandbox_exit_code,
                evidence,
            )
            if status == "fail":
                unmet.append(criterion)

            checks.append(
                VerificationCheck(
                    criterion=criterion,
                    status=status,
                    notes=notes,
                )
            )

        # Check if forbidden shortcuts were respected
        for shortcut in contract.forbidden_shortcuts:
            shortcut_kw = keyword_set(shortcut)
            text_kw = keyword_set(text)
            # We look for evidence the shortcut was violated
            # (this is a heuristic; real violation detection would be more sophisticated)
            # For now, we just record the check

        # Determine verdict
        passed = sum(1 for c in checks if c.status == "pass")
        total = len(checks)
        pass_rate = passed / total if total > 0 else 0.0

        verdict = (
            VerificationVerdict.PASS if pass_rate >= 0.7
            else VerificationVerdict.FAIL
        )

        # Collect evidence IDs referenced
        if evidence:
            for item in evidence.items:
                if item.excerpt and item.excerpt[:50] in text:
                    cited_evidence.append(item.evidence_id)

        # Independent findings (patterns suggesting issues)
        independent_findings: list[str] = []
        if not execution.declared_uncertainties and contract.constraints:
            independent_findings.append(
                "No uncertainties declared despite having constraints."
            )
        if execution.structured_output.get("llm_request_failed"):
            independent_findings.append(
                "Configured LLM endpoint request failed before the executor produced a usable artifact."
            )
        if execution.structured_output.get("offline_mode"):
            independent_findings.append(
                "Executor ran in offline mode, so the run did not produce a live model-backed artifact."
            )
        if sandbox.get("protocol_violation"):
            independent_findings.append(
                "Executor violated the code-output protocol by returning neither FILE blocks nor NO_CHANGES_NEEDED."
            )

        report = VerificationReport(
            verdict=verdict,
            summary=f"{passed}/{total} criteria passed ({pass_rate:.0%})",
            checks=checks,
            unmet_criteria=unmet,
            confidence=pass_rate,
            fresh_context_notes="Verification performed independently on output text.",
            cited_evidence_ids=cited_evidence,
            independent_findings=independent_findings,
        )

        return report

    # ── Composite evaluation ──────────────────────────────────────────

    def evaluate_run(
        self,
        contract: TaskContract,
        execution: ExecutionArtifact,
        dialectic: DialecticArtifact,
        verification: VerificationReport,
        evidence: EvidenceBundle | None = None,
        prior_champion_score: float = 0.0,
    ) -> RunEvaluation:
        """Produce a composite RunEvaluation using the contract rubric."""
        slop = self.slop_scorer.score(
            contract=contract,
            execution=execution,
            dialectic=dialectic,
            evidence=evidence,
        )

        # Task success: based on verification
        passed = sum(1 for c in verification.checks if c.status == "pass")
        total = len(verification.checks) if verification.checks else 1
        task_success = passed / total

        # Groundedness: inverse of unsupported_claims slop
        groundedness = _bounded01(1.0 - slop.unsupported_claims)

        # Objection coverage: how many objections were addressed
        parser_gap = (
            not dialectic.objection_ledger
            and _has_unparsed_antithesis_objections(dialectic.antithesis_summary)
        )
        if dialectic.objection_ledger:
            addressed = sum(
                1 for o in dialectic.objection_ledger
                if o.accepted is not None
            )
            objection_coverage = _bounded01(addressed / len(dialectic.objection_ledger))
        elif parser_gap:
            objection_coverage = 0.0
        else:
            objection_coverage = 1.0  # No objections = no gap

        # Unsupported assertion rate
        unsupported_assertion_rate = _bounded01(slop.unsupported_claims)

        # Redundancy rate
        redundancy_rate = _bounded01(slop.repetition_without_progress)

        # Novelty usefulness (proxy: inverse of shallow_novelty + benchmark_gaming)
        novelty_usefulness = _bounded01(1.0 - (
            slop.shallow_novelty * 0.5 + slop.benchmark_gaming * 0.5
        ))

        # Requirement fidelity
        requirement_fidelity = _bounded01(1.0 - slop.requirement_drift)

        # Verification quality
        verification_quality = _bounded01(verification.confidence)

        # Regression vs prior champion
        regression_vs_prior_champion = 0.0
        # Will be updated after computing overall_score

        # Compute overall score using contract rubric
        rubric = contract.evaluation_rubric
        score_components = {
            "task_success": task_success,
            "groundedness": groundedness,
            "objection_coverage": objection_coverage,
            "unsupported_assertion_rate": 1.0 - unsupported_assertion_rate,
            "redundancy_rate": 1.0 - redundancy_rate,
            "novelty_usefulness": novelty_usefulness,
            "requirement_fidelity": requirement_fidelity,
            "verification_quality": verification_quality,
        }

        overall = 0.0
        total_weight = 0.0
        for metric_name, weight in rubric.items():
            value = score_components.get(metric_name, 0.0)
            overall += value * weight
            total_weight += weight
        overall = _bounded01(overall / total_weight if total_weight > 0 else 0.0)

        # Regression check
        if prior_champion_score > 0:
            regression_vs_prior_champion = max(
                0.0, prior_champion_score - overall
            )

        # Accept decision
        accepted = (
            verification.verdict == VerificationVerdict.PASS
            and overall >= 0.6
            and slop.composite < 0.4
        )

        notes: list[str] = []
        if parser_gap:
            notes.append(
                "Antithesis contained objection text but no structured objections were parsed."
            )
        if regression_vs_prior_champion > 0.1:
            notes.append(
                f"Significant regression vs champion: {regression_vs_prior_champion:.2f}"
            )
        if slop.composite > 0.3:
            notes.append(f"Elevated slop: {slop.composite:.2f}")

        return RunEvaluation(
            task_success=task_success,
            groundedness=groundedness,
            objection_coverage=objection_coverage,
            unsupported_assertion_rate=unsupported_assertion_rate,
            redundancy_rate=redundancy_rate,
            novelty_usefulness=novelty_usefulness,
            requirement_fidelity=requirement_fidelity,
            verification_quality=verification_quality,
            regression_vs_prior_champion=regression_vs_prior_champion,
            slop=slop,
            overall_score=overall,
            accepted=accepted,
            notes=notes,
        )
