"""Tests for the contract compiler."""

import pytest

from autodialectics.contract.compiler import ContractCompiler
from autodialectics.schemas import TaskDomain, TaskSubmission


@pytest.fixture()
def compiler() -> ContractCompiler:
    return ContractCompiler()


def test_domain_inference_code(compiler: ContractCompiler) -> None:
    """Keywords like 'bug', 'refactor', 'code' should infer CODE domain."""
    sub = TaskSubmission(
        title="Fix bug in code",
        description="Refactor the module to fix the issue.",
    )
    assert compiler.infer_domain(sub) == TaskDomain.CODE


def test_domain_inference_research(compiler: ContractCompiler) -> None:
    """Keywords like 'paper', 'citation' should infer RESEARCH domain."""
    sub = TaskSubmission(
        title="Literature review on topic",
        description="Cite relevant papers and provide citations.",
    )
    assert compiler.infer_domain(sub) == TaskDomain.RESEARCH


def test_domain_inference_writing(compiler: ContractCompiler) -> None:
    """Keywords like 'essay', 'draft' should infer WRITING domain."""
    sub = TaskSubmission(
        title="Write an essay",
        description="Draft a document for the report.",
    )
    assert compiler.infer_domain(sub) == TaskDomain.WRITING


def test_domain_inference_experiment(compiler: ContractCompiler) -> None:
    """Keywords like 'benchmark', 'optimizer' should infer EXPERIMENT domain."""
    sub = TaskSubmission(
        title="Benchmark the optimizer",
        description="Run a measurement and simulation experiment.",
    )
    assert compiler.infer_domain(sub) == TaskDomain.EXPERIMENT


def test_domain_inference_analysis(compiler: ContractCompiler) -> None:
    """Keywords like 'analyze', 'logs' should infer ANALYSIS domain."""
    sub = TaskSubmission(
        title="Analyze the logs",
        description="Investigate metrics and trends in the data.",
    )
    assert compiler.infer_domain(sub) == TaskDomain.ANALYSIS


def test_domain_inference_generic(compiler: ContractCompiler) -> None:
    """No keyword match should fall back to GENERIC."""
    sub = TaskSubmission(
        title="Do something",
        description="Complete the requested item quickly.",
    )
    assert compiler.infer_domain(sub) == TaskDomain.GENERIC


def test_explicit_domain(compiler: ContractCompiler) -> None:
    """If domain is set explicitly, use it regardless of keywords."""
    sub = TaskSubmission(
        title="Fix bug in code",
        description="Refactor the module.",
        domain=TaskDomain.WRITING,
    )
    assert compiler.infer_domain(sub) == TaskDomain.WRITING


def test_contract_is_immutable(compiler: ContractCompiler) -> None:
    """Compiling the same submission twice should produce the same source_hash."""
    sub = TaskSubmission(
        title="Immutable test",
        description="Same description both times.",
    )
    c1 = compiler.compile(sub)
    c2 = compiler.compile(sub)
    assert c1.source_hash == c2.source_hash
    # But contract_id should differ (each compilation is a new instance)
    # Actually in this implementation they use default_factory so they will differ


def test_contract_deliverables_include_defaults(compiler: ContractCompiler) -> None:
    """Code domain contracts should include domain-default deliverables."""
    sub = TaskSubmission(
        title="Code task",
        description="Implement something.",
    )
    contract = compiler.compile(sub)
    assert len(contract.deliverables) > 0
    # Code domain defaults include "Working implementation with passing tests."
    assert any("test" in d.lower() for d in contract.deliverables)
    # And "Documentation of design decisions and trade-offs."
    assert any("documentation" in d.lower() for d in contract.deliverables)


def test_contract_forbidden_shortcuts_include_common(compiler: ContractCompiler) -> None:
    """All contracts should include the 5 common forbidden shortcuts."""
    sub = TaskSubmission(
        title="Any task",
        description="Do something.",
    )
    contract = compiler.compile(sub)
    # Check that common shortcuts are present
    assert any("Do not claim completion" in s for s in contract.forbidden_shortcuts)
    assert any("Do not invent citations" in s for s in contract.forbidden_shortcuts)
    assert any("Do not silently rewrite objectives" in s for s in contract.forbidden_shortcuts)
    assert any("Do not suppress uncertainty" in s for s in contract.forbidden_shortcuts)
    assert any("Do not treat scratchpad notes" in s for s in contract.forbidden_shortcuts)


def test_contract_has_evaluation_rubric(compiler: ContractCompiler) -> None:
    """The evaluation rubric weights should sum to approximately 1.0."""
    sub = TaskSubmission(
        title="Rubric test",
        description="Verify rubric sums to ~1.0.",
    )
    contract = compiler.compile(sub)
    total = sum(contract.evaluation_rubric.values())
    assert abs(total - 1.0) < 0.02, f"Rubric weights sum to {total}, expected ~1.0"
