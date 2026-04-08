"""Tests for sandboxed code execution and verification."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from autodialectics.contract.compiler import ContractCompiler
from autodialectics.evaluation.slop import RunEvaluator
from autodialectics.execution.adapters import CodeAdapter, _materialize_workspace
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


class SequenceFakeModelClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.prompts: list[str] = []

    def complete(self, role: str, system_prompt: str, user_prompt: str) -> ModelResponse:
        self.prompts.append(user_prompt)
        index = min(len(self.prompts) - 1, len(self.contents) - 1)
        return ModelResponse(content=self.contents[index])


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


def _compile_code_contract(
    workspace: Path,
    *,
    workspace_root: Path | None = None,
    verification_commands: list[str] | None = None,
    max_repair_attempts: int | None = None,
):
    submission = TaskSubmission(
        title="Fix calculator division by zero",
        description="Apply the fix and verify it with tests.",
        domain=TaskDomain.CODE,
        workspace_root=str(workspace_root) if workspace_root else None,
        verification_commands=verification_commands or [],
        max_repair_attempts=max_repair_attempts,
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


def test_code_adapter_verifies_existing_workspace_when_no_file_blocks_are_returned(tmp_path: Path) -> None:
    workspace = _seed_code_workspace(tmp_path)
    (workspace / "calculator.py").write_text(
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError('division by zero')\n"
        "    return a / b\n",
        encoding="utf-8",
    )
    contract = _compile_code_contract(workspace)
    adapter = CodeAdapter()

    execution = adapter.execute(
        contract,
        EvidenceBundle(summary=""),
        _dialectic(),
        FakeModelClient("NO_CHANGES_NEEDED\nThe implementation already satisfies the task."),
    )

    sandbox = execution.structured_output["sandbox"]
    assert execution.status == "completed"
    assert sandbox["applied"] is False
    assert sandbox["no_op_verification"] is True
    assert sandbox["test_exit_code"] == 0
    assert "test_calculator.py" in sandbox["verification_targets"]


def test_code_adapter_fails_when_executor_request_fails_even_if_existing_tests_are_green(
    tmp_path: Path,
) -> None:
    workspace = _seed_code_workspace(tmp_path)
    (workspace / "calculator.py").write_text(
        "def divide(a, b):\n"
        "    if b == 0:\n"
        "        raise ValueError('division by zero')\n"
        "    return a / b\n",
        encoding="utf-8",
    )
    contract = _compile_code_contract(workspace)
    adapter = CodeAdapter()

    execution = adapter.execute(
        contract,
        EvidenceBundle(summary=""),
        _dialectic(),
        FakeModelClient(
            "[LLM REQUEST FAILED] Connection to configured endpoint failed: http://127.0.0.1:8642. "
            "Role: executor. The system fell back because the configured endpoint did not produce a usable response."
        ),
    )

    sandbox = execution.structured_output["sandbox"]
    assert execution.status == "failed"
    assert execution.structured_output["llm_request_failed"] is True
    assert sandbox["test_exit_code"] == 0
    assert sandbox["protocol_violation"] is True


def test_code_adapter_fails_when_executor_omits_file_blocks_and_no_op_marker(tmp_path: Path) -> None:
    workspace = _seed_code_workspace(tmp_path)
    contract = _compile_code_contract(workspace)
    adapter = CodeAdapter()

    execution = adapter.execute(
        contract,
        EvidenceBundle(summary=""),
        _dialectic(),
        FakeModelClient("Implemented the fix but forgot to include the file payload."),
    )

    sandbox = execution.structured_output["sandbox"]
    assert execution.status == "failed"
    assert sandbox["protocol_violation"] is True


def test_code_adapter_uses_explicit_workspace_root_and_verification_commands(tmp_path: Path) -> None:
    workspace = _seed_code_workspace(tmp_path)
    contract = _compile_code_contract(
        workspace,
        workspace_root=workspace,
        verification_commands=["python -m pytest -q test_calculator.py"],
    )
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
    assert sandbox["copied_assets"] == [workspace.name]
    assert sandbox["test_command"] == "python -m pytest -q test_calculator.py"
    assert sandbox["verification_runs"][0]["command"] == "python -m pytest -q test_calculator.py"


def test_code_adapter_retries_failed_attempts_with_current_candidate_context(tmp_path: Path) -> None:
    workspace = _seed_code_workspace(tmp_path)
    contract = _compile_code_contract(
        workspace,
        workspace_root=workspace,
        verification_commands=["python -m pytest -q test_calculator.py"],
        max_repair_attempts=2,
    )
    adapter = CodeAdapter()
    model = SequenceFakeModelClient(
        [
            (
                "Tried a change.\n\n"
                "FILE: calculator.py\n```python\n"
                "def divide(a, b):\n"
                "    return a / b\n"
                "```\n"
            ),
            (
                "Fixed the failing implementation.\n\n"
                "FILE: calculator.py\n```python\n"
                "def divide(a, b):\n"
                "    if b == 0:\n"
                "        raise ValueError('division by zero')\n"
                "    return a / b\n"
                "```\n"
            ),
        ]
    )

    execution = adapter.execute(
        contract,
        EvidenceBundle(summary=""),
        _dialectic(),
        model,
    )

    sandbox = execution.structured_output["sandbox"]
    attempts = execution.structured_output["attempts"]
    assert execution.status == "completed"
    assert len(model.prompts) == 2
    assert len(attempts) == 2
    assert attempts[0]["test_exit_code"] != 0
    assert attempts[1]["test_exit_code"] == 0
    assert "Workspace Context" in model.prompts[0]
    assert "test_calculator.py" in model.prompts[0]
    assert "Previous Attempt Failed" in model.prompts[1]
    assert "Current Candidate Files" in model.prompts[1]
    assert sandbox["test_exit_code"] == 0


def test_materialize_workspace_avoids_colliding_mount_names(tmp_path: Path) -> None:
    left_root = tmp_path / "alpha" / "workspace"
    right_root = tmp_path / "beta" / "workspace"
    left_root.mkdir(parents=True)
    right_root.mkdir(parents=True)
    (left_root / "main.py").write_text("LEFT = True\n", encoding="utf-8")
    (right_root / "main.py").write_text("RIGHT = True\n", encoding="utf-8")

    assets = [
        AssetRef(
            kind=AssetKind.FILE,
            location=str(left_root / "main.py"),
            label=f"left-{uuid4().hex[:6]}",
        ),
        AssetRef(
            kind=AssetKind.FILE,
            location=str(right_root / "main.py"),
            label=f"right-{uuid4().hex[:6]}",
        ),
    ]

    copied = _materialize_workspace(assets, tmp_path / "sandbox")

    assert len(copied) == 2
    assert copied[0] != copied[1]
    copied_contents = {
        mount_name: (tmp_path / "sandbox" / mount_name / "main.py").read_text(encoding="utf-8")
        for mount_name in copied
    }
    assert sorted(copied_contents.values()) == ["LEFT = True\n", "RIGHT = True\n"]
