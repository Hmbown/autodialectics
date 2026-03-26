"""Tests that evaluation does not give free credit when objections were not parsed."""

from __future__ import annotations

from autodialectics.contract.compiler import ContractCompiler
from autodialectics.evaluation.slop import RunEvaluator
from autodialectics.schemas import (
    DialecticArtifact,
    ExecutionArtifact,
    TaskSubmission,
    VerificationReport,
    VerificationVerdict,
)


def _contract():
    submission = TaskSubmission(
        title="Research attention mechanisms",
        description="Produce a synthesis.",
    )
    return ContractCompiler().compile(submission)


def test_evaluate_run_flags_parser_gap_when_antithesis_has_objections_but_ledger_is_empty() -> None:
    contract = _contract()
    dialectic = DialecticArtifact(
        thesis="1. Draft a plan",
        antithesis_summary=(
            "## Objections\n\n"
            "1. **Claim being challenged:** The plan is ready.  \n"
            "   **Objection:** It ignores evidence gaps.  \n"
            "   **Severity:** 0.9"
        ),
        synthesis="1. Revised plan",
        synthesis_steps=["Revised plan"],
    )
    execution = ExecutionArtifact(output_text="A draft answer with no evidence.")
    verification = VerificationReport(
        verdict=VerificationVerdict.FAIL,
        checks=[],
        confidence=0.0,
    )

    evaluation = RunEvaluator().evaluate_run(
        contract,
        execution,
        dialectic,
        verification,
    )

    assert evaluation.objection_coverage == 0.0
    assert any("no structured objections were parsed" in note.lower() for note in evaluation.notes)
