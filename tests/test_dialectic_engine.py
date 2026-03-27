"""Targeted tests for live-dialectic parsing and objection handoff."""

from __future__ import annotations

from autodialectics.contract.compiler import ContractCompiler
from autodialectics.dialectic.engine import DialecticalPlanner, _parse_antithesis
from autodialectics.routing.cliproxy import ModelResponse
from autodialectics.schemas import EvidenceBundle, ObjectionRecord, TaskSubmission


class StaticModelClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.offline = False

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> ModelResponse:
        return ModelResponse(content=self.content)


class CapturingModelClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.offline = False
        self.calls: list[tuple[str, str, str]] = []

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> ModelResponse:
        self.calls.append((role, system_prompt, user_prompt))
        return ModelResponse(content=self.content)


def _contract():
    submission = TaskSubmission(
        title="Research attention mechanisms",
        description="Produce a synthesis.",
    )
    return ContractCompiler().compile(submission)


def test_llm_antithesis_parses_markdown_claim_objection_and_severity_blocks() -> None:
    antithesis_text = """
Here are the main objections.

### 1) Claim being challenged: Define the scope first.

**Objection**
The scope is too fuzzy and mixes multiple axes.
It will cause category errors later.

**Severity**: 0.92

### 2) Claim being challenged: Build a source acquisition plan.

**Objection**
The plan gathers papers before setting evaluation standards.

**Severity**: 0.67
""".strip()
    planner = DialecticalPlanner(model_client=StaticModelClient(antithesis_text))

    summary, objections = planner._llm_antithesis(
        _contract(),
        EvidenceBundle(summary="thin evidence"),
        ("1. Draft a plan", ["Draft a plan"]),
        "Critique the plan.",
    )

    assert summary == antithesis_text
    assert len(objections) == 2
    assert objections[0].claim == "Define the scope first."
    assert "mixes multiple axes" in objections[0].objection
    assert objections[0].severity == 0.92
    assert objections[1].claim == "Build a source acquisition plan."
    assert "evaluation standards" in objections[1].objection
    assert objections[1].severity == 0.67


def test_llm_synthesis_includes_raw_antithesis_when_structured_objections_are_empty() -> None:
    client = CapturingModelClient("1. Revised plan\n2. Address objections explicitly")
    planner = DialecticalPlanner(model_client=client)
    antithesis_text = "Claim being challenged: The plan is ready.\nObjection: It ignores evidence gaps.\nSeverity: 0.8"

    artifact = planner._llm_synthesis(
        _contract(),
        EvidenceBundle(summary="thin evidence"),
        ("1. Draft a plan", ["Draft a plan"]),
        (antithesis_text, []),
        "Reconcile the objections.",
    )

    assert artifact.synthesis_steps == ["Revised plan", "Address objections explicitly"]
    assert client.calls
    _, _, user_prompt = client.calls[0]
    assert antithesis_text in user_prompt
    assert "It ignores evidence gaps." in user_prompt


class FailureThenUnexpectedClient:
    def __init__(self) -> None:
        self.offline = False
        self.calls = 0

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                content="[LLM REQUEST FAILED] Configured endpoint returned HTTP 503"
            )
        return ModelResponse(content="1. This should never be used")


def test_plan_falls_back_to_heuristic_when_llm_request_fails() -> None:
    planner = DialecticalPlanner(model_client=FailureThenUnexpectedClient())
    artifact = planner.plan(_contract(), EvidenceBundle(summary="thin evidence"))

    assert artifact.thesis.startswith("Plan (heuristic):")
    assert artifact.synthesis.startswith("Revised plan (heuristic synthesis):")


def test_parse_antithesis_accepts_markdown_table_rows() -> None:
    objections = _parse_antithesis(
        "\n".join(
            [
                "| # | claim | objection | severity |",
                "| 1 | Define scope first | Scope is too broad | 0.8 |",
                "| 2 | Run evaluation | Missing baseline and guardrails | 0.6 |",
            ]
        )
    )

    assert len(objections) == 2
    assert objections[0].claim == "Define scope first"
    assert objections[0].severity == 0.8
    assert objections[1].objection == "Missing baseline and guardrails"


def test_llm_synthesis_leaves_unaddressed_high_severity_objections_unresolved() -> None:
    client = CapturingModelClient("1. Keep the original plan\n2. Add a short conclusion")
    planner = DialecticalPlanner(model_client=client)

    artifact = planner._llm_synthesis(
        _contract(),
        EvidenceBundle(summary="thin evidence"),
        ("1. Draft a plan", ["Draft a plan"]),
        (
            "Claim being challenged: The scope is sufficient.\n"
            "Objection: The plan ignores evidence gaps and benchmarking requirements.\n"
            "Severity: 0.95",
            [
                ObjectionRecord(
                    claim="The scope is sufficient.",
                    objection="The plan ignores evidence gaps and benchmarking requirements.",
                    severity=0.95,
                )
            ],
        ),
        "Reconcile the objections.",
    )

    assert artifact.objection_ledger[0].accepted is False
    assert artifact.unresolved_questions == [
        "The plan ignores evidence gaps and benchmarking requirements."
    ]
