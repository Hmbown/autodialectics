"""Tests for sandboxed code execution and verification."""

from __future__ import annotations

from pathlib import Path

from autodialectics.contract.compiler import ContractCompiler
from autodialectics.evaluation.slop import RunEvaluator
from autodialectics.execution.adapters import CodeAdapter
from autodialectics.routing.cliproxy import ModelResponse
from autodialectics.schemas import (
    AssetKind,
    AssetRef,
    DialecticArtifact,
    EvidenceBundle,
    ExecutionArtifact,
    TaskDomain,
    TaskSubmission,
)


class FakeModelClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> ModelResponse:
        return ModelResponse(content=self.content)


def _seed_code_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "calculator.py").write_text(
        "def divide(a, b):\n    return a / b\n",
        encoding="utf-8",
    )
    (workspace / "test_calculator.py").write_text(
        "import pytest\n\n"
        "from calculator import divide\n\n\n"
        "def test_divide_by_zero_raises_value_error():\n"
        "    with pytest.raises(ValueError, match='division by zero'):\n"
        "        divide(10, 0)\n",
        encoding="utf-8",
    )
    return workspace


def _compile_code_contract(workspace: Path):
    submission = TaskSubmission(
        title="Fix calculator division by zero",
        description="Apply the fix and verify it with tests.",
        domain=TaskDomain.CODE,
        assets=[
            AssetRef(
                kind=AssetKind.FILE,
                location=str(workspace / "calculator.py"),
                label="calculator.py",
            )
        ],
    )
    return ContractCompiler().compile(submission)


def _dialectic() -> DialecticArtifact:
    return DialecticArtifact(
        thesis="Edit calculator.py.",
        synthesis="Replace divide with a zero-safe implementation.",
    )


def test_code_adapter_applies_changes_in_isolated_workspace_and_runs_tests(tmp_path: Path) -> None:
    workspace = _seed_code_workspace(tmp_path)
    contract = _compile_code_contract(workspace)
    adapter = CodeAdapter()
    response = (
        "Implemented the fix.\n\n"
        "FILE: calculator.py\n```python\n"
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError('division by zero')\n"
        "    return a / b\n"
        "```\n"
    )

    execution = adapter.execute(
        contract,
        EvidenceBundle(summary=""),
        _dialectic(),
        FakeModelClient(response),
    )

    sandbox = execution.structured_output["sandbox"]
    assert execution.status == "completed"
    assert sandbox["applied"] is True
    assert sandbox["test_exit_code"] == 0
    assert "pytest" in (sandbox["test_command"] or "")
    assert sandbox["verification_targets"] == ["test_calculator.py"]
    assert any("a/calculator.py" in patch for patch in execution.patches)
    assert "return a / b" in (workspace / "calculator.py").read_text(encoding="utf-8")


def test_code_adapter_captures_failed_sandbox_verification(tmp_path: Path) -> None:
    workspace = _seed_code_workspace(tmp_path)
    contract = _compile_code_contract(workspace)
    adapter = CodeAdapter()
    response = (
        "Tried a change.\n\n"
        "FILE: calculator.py\n```python\n"
        "def divide(a, b):\n"
        "    return a / b\n"
        "```\n"
    )

    execution = adapter.execute(
        contract,
        EvidenceBundle(summary=""),
        _dialectic(),
        FakeModelClient(response),
    )

    sandbox = execution.structured_output["sandbox"]
    assert execution.status == "failed"
    assert sandbox["test_exit_code"] != 0
    assert execution.test_results
    assert "failed" in execution.test_results[0].lower()
    assert "return a / b" in (workspace / "calculator.py").read_text(encoding="utf-8")


def test_run_evaluator_uses_sandbox_verification_for_code_tasks(tmp_path: Path) -> None:
    contract = _compile_code_contract(_seed_code_workspace(tmp_path))
    execution = ExecutionArtifact(
        output_text="Implemented calculator fix.",
        structured_output={
            "sandbox": {
                "test_command": "python -m pytest -q test_calculator.py",
                "test_exit_code": 0,
            }
        },
    )

    report = RunEvaluator().verify(contract, execution, evidence=EvidenceBundle(summary=""))

    sandbox_checks = [
        check for check in report.checks if check.criterion == "Sandbox verification tests pass"
    ]
    assert sandbox_checks
    assert sandbox_checks[0].status == "pass"
