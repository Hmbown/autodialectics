"""Domain-specific execution adapters and registry."""

from __future__ import annotations

import difflib
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autodialectics.execution.base import ExecutionAdapter
from autodialectics.schemas import (
    DialecticArtifact,
    EvidenceBundle,
    ExecutionArtifact,
    TaskDomain,
    TaskContract,
)

if TYPE_CHECKING:
    from autodialectics.routing.cliproxy import ModelClient

logger = logging.getLogger(__name__)


# ── Generic Adapter ───────────────────────────────────────────────────


class GenericAdapter(ExecutionAdapter):
    """Default fallback adapter for any domain."""

    name = "generic"

    def execute(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: DialecticArtifact,
        model_client: ModelClient,
        policy_surfaces: dict[str, str] | None = None,
    ) -> ExecutionArtifact:
        system = (
            "You are a task execution assistant. Execute the plan below, "
            "following all constraints and producing all required deliverables. "
            "Be precise and ground your work in the provided evidence."
        )
        user = self._build_user_prompt(contract, evidence, dialectic)
        resp = model_client.complete(
            role="executor", system_prompt=system, user_prompt=user
        )
        return self._parse_response(resp.content)


class CodeAdapter(ExecutionAdapter):
    """Adapter for code implementation tasks."""

    name = "code"

    def execute(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: DialecticArtifact,
        model_client: ModelClient,
        policy_surfaces: dict[str, str] | None = None,
    ) -> ExecutionArtifact:
        system = (
            "You are a software engineering assistant. Implement the required "
            "code changes following the plan. Produce working code that passes "
            "all specified tests. Include any new or modified files in your "
            "response. Do not stub or skip functionality."
        )
        user = self._build_user_prompt(contract, evidence, dialectic)
        user += (
            "\n\nIMPORTANT: Output all code changes clearly. "
            "For each file, use the format:\n"
            "FILE: path/to/file.py\n```python\n<code>\n```\n"
            "Use repository-relative paths only. Do not describe a patch without "
            "including the full replacement content for each changed file."
        )
        resp = model_client.complete(
            role="executor", system_prompt=system, user_prompt=user
        )
        execution = self._parse_response(resp.content, domain="code")
        file_blocks = _extract_file_blocks(resp.content)
        if not file_blocks:
            execution.status = "failed"
            execution.tool_log.append(
                "No sandbox run: executor response did not include FILE blocks."
            )
            execution.structured_output = {
                "sandbox": {
                    "applied": False,
                    "reason": "No FILE blocks found in executor response.",
                }
            }
            return execution

        return _apply_code_changes_in_sandbox(
            contract=contract,
            execution=execution,
            file_blocks=file_blocks,
        )


class ResearchAdapter(ExecutionAdapter):
    """Adapter for research tasks."""

    name = "research"

    def execute(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: DialecticArtifact,
        model_client: ModelClient,
        policy_surfaces: dict[str, str] | None = None,
    ) -> ExecutionArtifact:
        system = (
            "You are a research assistant. Produce a structured findings "
            "document. For each factual claim, cite the supporting source. "
            "Clearly distinguish established facts from inferences. "
            "Acknowledge contradictory evidence.\n\n"
            "Structure your response with:\n"
            "## Claims and Evidence\n"
            "For each claim: [CLAIM] - Evidence: [source/reasoning]\n\n"
            "## Inferences\n"
            "For each inference: [INFERENCE] - Based on: [evidence]\n\n"
            "## Gaps and Uncertainties\n"
            "List what remains unknown or unverified."
        )
        user = self._build_user_prompt(contract, evidence, dialectic)
        resp = model_client.complete(
            role="executor", system_prompt=system, user_prompt=user
        )
        return self._parse_response(resp.content, domain="research")


class WritingAdapter(ExecutionAdapter):
    """Adapter for writing/revision tasks."""

    name = "writing"

    def execute(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: DialecticArtifact,
        model_client: ModelClient,
        policy_surfaces: dict[str, str] | None = None,
    ) -> ExecutionArtifact:
        system = (
            "You are a writing and revision assistant. Produce or revise "
            "the document as specified. Follow the style, tone, and "
            "formatting requirements. Do not pad content unnecessarily. "
            "Every paragraph should advance the document's purpose.\n\n"
            "Output the complete revised document. End with a summary "
            "of substantive changes made."
        )
        user = self._build_user_prompt(contract, evidence, dialectic)
        resp = model_client.complete(
            role="executor", system_prompt=system, user_prompt=user
        )
        return self._parse_response(resp.content, domain="writing")


class ExperimentAdapter(ExecutionAdapter):
    """Adapter for experiment design tasks."""

    name = "experiment"

    def execute(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: DialecticArtifact,
        model_client: ModelClient,
        policy_surfaces: dict[str, str] | None = None,
    ) -> ExecutionArtifact:
        system = (
            "You are an experiment design and analysis assistant. "
            "Design a reproducible experiment protocol. Specify:\n"
            "1. Hypothesis\n"
            "2. Variables (independent, dependent, controlled)\n"
            "3. Procedure (step-by-step, fully reproducible)\n"
            "4. Data collection plan\n"
            "5. Analysis method (with statistical tests if applicable)\n"
            "6. Expected outcomes and interpretation criteria\n\n"
            "Do not fabricate data. If reporting results, include actual data."
        )
        user = self._build_user_prompt(contract, evidence, dialectic)
        resp = model_client.complete(
            role="executor", system_prompt=system, user_prompt=user
        )
        return self._parse_response(resp.content, domain="experiment")


class AnalysisAdapter(ExecutionAdapter):
    """Adapter for analysis tasks."""

    name = "analysis"

    def execute(
        self,
        contract: TaskContract,
        evidence: EvidenceBundle,
        dialectic: DialecticArtifact,
        model_client: ModelClient,
        policy_surfaces: dict[str, str] | None = None,
    ) -> ExecutionArtifact:
        system = (
            "You are an analytical assistant. Produce a structured analysis "
            "memo. Consider multiple interpretations of the data. "
            "Tie all conclusions to specific evidence.\n\n"
            "Structure:\n"
            "## Summary\n"
            "## Key Findings\n"
            "## Analysis (with supporting evidence for each point)\n"
            "## Alternative Interpretations\n"
            "## Conclusions (with confidence level)\n"
            "## Limitations and Caveats"
        )
        user = self._build_user_prompt(contract, evidence, dialectic)
        resp = model_client.complete(
            role="executor", system_prompt=system, user_prompt=user
        )
        return self._parse_response(resp.content, domain="analysis")


# ── Adapter Registry ──────────────────────────────────────────────────


class AdapterRegistry:
    """Registry mapping TaskDomain to ExecutionAdapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[TaskDomain, ExecutionAdapter] = {
            TaskDomain.CODE: CodeAdapter(),
            TaskDomain.RESEARCH: ResearchAdapter(),
            TaskDomain.WRITING: WritingAdapter(),
            TaskDomain.EXPERIMENT: ExperimentAdapter(),
            TaskDomain.ANALYSIS: AnalysisAdapter(),
            TaskDomain.GENERIC: GenericAdapter(),
        }

    def for_domain(self, domain: TaskDomain) -> ExecutionAdapter:
        """Return the adapter for the given domain, falling back to Generic."""
        adapter = self._adapters.get(domain)
        if adapter is None:
            logger.warning(
                "No adapter for domain %s, falling back to GenericAdapter",
                domain,
            )
            return self._adapters[TaskDomain.GENERIC]
        return adapter

    def register(
        self, domain: TaskDomain, adapter: ExecutionAdapter
    ) -> None:
        """Register a custom adapter for a domain."""
        self._adapters[domain] = adapter
        logger.info("Registered adapter '%s' for domain %s", adapter.name, domain)


def _extract_file_blocks(content: str) -> dict[str, str]:
    """Extract FILE blocks containing replacement file contents."""
    import re

    block_pattern = re.compile(
        r"^FILE:\s*(?P<path>[^\n]+)\n```(?:[^\n]*)\n(?P<body>.*?)\n```",
        re.MULTILINE | re.DOTALL,
    )
    files: dict[str, str] = {}
    for match in block_pattern.finditer(content):
        rel_path = match.group("path").strip()
        files[rel_path] = match.group("body")
    return files


def _copy_tree_contents(src: Path, dest: Path) -> None:
    """Copy a directory tree into dest without nesting an extra top-level directory."""
    for child in src.iterdir():
        target = dest / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)


def _materialize_workspace(assets: list[Any], workspace_root: Path) -> list[str]:
    """Copy code assets into an isolated workspace for sandboxed execution."""
    from autodialectics.schemas import AssetKind

    copied: list[str] = []
    source_roots: list[Path] = []

    for asset in assets:
        if not asset.location:
            continue
        source = Path(asset.location).resolve()
        if asset.kind == AssetKind.DIRECTORY and source.is_dir():
            source_roots.append(source)
        elif asset.kind in {AssetKind.FILE, AssetKind.JSON} and source.is_file():
            source_roots.append(source.parent)

    unique_roots: list[Path] = []
    seen_roots: set[str] = set()
    for root in source_roots:
        key = str(root)
        if key not in seen_roots:
            seen_roots.add(key)
            unique_roots.append(root)

    if len(unique_roots) == 1:
        root = unique_roots[0]
        _copy_tree_contents(root, workspace_root)
        copied.append(root.name)
        return copied

    for root in unique_roots:
        target = workspace_root / root.name
        shutil.copytree(root, target, dirs_exist_ok=True)
        copied.append(root.name)

    return copied


def _safe_workspace_path(workspace_root: Path, rel_path: str) -> Path:
    """Resolve a repository-relative path inside the sandbox workspace."""
    candidate = Path(rel_path.strip())
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe file path in executor output: {rel_path}")
    return workspace_root / candidate


def _build_patch(rel_path: str, before: str, after: str) -> str:
    """Return a unified diff for a changed file."""
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
    )
    return "".join(diff)


def _select_verification_command(
    workspace_root: Path,
    changed_files: list[str],
) -> tuple[list[str] | None, list[str]]:
    """Choose the narrowest useful verification command for the sandbox."""
    discovered_tests = sorted(
        path.relative_to(workspace_root).as_posix()
        for path in workspace_root.rglob("*.py")
        if path.is_file()
        and "__pycache__" not in path.parts
        and (path.name.startswith("test_") or path.name.endswith("_test.py"))
    )
    if discovered_tests:
        changed_stems = {Path(path).stem for path in changed_files}
        related_tests = [
            test_path
            for test_path in discovered_tests
            if changed_stems & set(Path(test_path).stem.replace("test_", "").split("."))
            or any(Path(changed).stem in test_path for changed in changed_files)
        ]
        targets = related_tests or discovered_tests
        return [sys.executable, "-m", "pytest", "-q", *targets], targets

    python_targets = [path for path in changed_files if path.endswith(".py")]
    if python_targets:
        return [sys.executable, "-m", "py_compile", *python_targets], python_targets

    return None, []


def _run_verification_command(
    command: list[str] | None,
    *,
    workspace_root: Path,
) -> tuple[int | None, str, str]:
    """Execute verification inside the sandbox workspace."""
    if not command:
        return None, "", ""

    completed = subprocess.run(
        command,
        cwd=workspace_root,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _apply_code_changes_in_sandbox(
    *,
    contract: TaskContract,
    execution: ExecutionArtifact,
    file_blocks: dict[str, str],
) -> ExecutionArtifact:
    """Materialize a sandbox workspace, apply model changes, and run verification."""
    with tempfile.TemporaryDirectory(prefix="autodialectics-code-") as tmpdir:
        workspace_root = Path(tmpdir) / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        copied_assets = _materialize_workspace(contract.relevant_assets, workspace_root)

        patches: list[str] = []
        applied_files: list[str] = []
        for rel_path, new_content in file_blocks.items():
            target = _safe_workspace_path(workspace_root, rel_path)
            before = target.read_text(encoding="utf-8") if target.exists() else ""
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content, encoding="utf-8")
            patch_text = _build_patch(rel_path, before, new_content)
            if patch_text:
                patches.append(patch_text)
            applied_files.append(rel_path)

        command, verification_targets = _select_verification_command(
            workspace_root, applied_files
        )
        exit_code, stdout, stderr = _run_verification_command(
            command, workspace_root=workspace_root
        )

        execution.created_files = applied_files
        execution.patches = patches
        execution.test_results = []
        if command is not None:
            command_text = " ".join(command)
            status_text = "passed" if exit_code == 0 else "failed"
            execution.test_results.append(
                f"Sandbox verification {status_text}: {command_text} (exit {exit_code})."
            )
            execution.tool_log.append(
                f"Executed sandbox verification command: {command_text}."
            )
        else:
            command_text = None
            execution.tool_log.append(
                "No verification command was available for sandboxed code changes."
            )

        execution.status = "completed" if exit_code in (None, 0) else "failed"
        execution.structured_output = {
            "sandbox": {
                "applied": True,
                "copied_assets": copied_assets,
                "applied_files": applied_files,
                "verification_targets": verification_targets,
                "test_command": command_text,
                "test_exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
            }
        }

        report_lines = [
            "",
            "SANDBOX REPORT",
            f"Applied files: {', '.join(applied_files) if applied_files else '(none)'}",
            f"Verification command: {command_text or 'none'}",
            f"Verification exit code: {exit_code if exit_code is not None else 'n/a'}",
        ]
        if stdout.strip():
            report_lines.append("Verification stdout:\n" + stdout.strip())
        if stderr.strip():
            report_lines.append("Verification stderr:\n" + stderr.strip())
        execution.output_text = execution.output_text + "\n" + "\n".join(report_lines)
        execution.summary = (
            execution.output_text[:500]
            if len(execution.output_text) > 500
            else execution.output_text
        )
        return execution


# ── Shared helpers ────────────────────────────────────────────────────


def _build_user_prompt(
    contract: TaskContract,
    evidence: EvidenceBundle,
    dialectic: DialecticArtifact,
) -> str:
    """Build the user prompt from contract, evidence, and dialectic."""
    parts = [
        f"# Task: {contract.title}",
        "",
        "## Objectives",
        "",
    ]
    for obj in contract.objectives:
        parts.append(f"- {obj}")

    if contract.constraints:
        parts += ["", "## Constraints", ""]
        for c in contract.constraints:
            parts.append(f"- {c}")

    if contract.deliverables:
        parts += ["", "## Deliverables", ""]
        for d in contract.deliverables:
            parts.append(f"- {d}")

    parts += [
        "",
        "## Forbidden Shortcuts",
        "",
    ]
    for s in contract.forbidden_shortcuts:
        parts.append(f"- {s}")

    if evidence.items:
        parts += ["", "## Evidence", ""]
        for item in evidence.items:
            parts.append(f"- [{item.source_path}] {item.excerpt[:300]}")

    parts += [
        "",
        "## Execution Plan (Dialectic Synthesis)",
        "",
        dialectic.synthesis,
    ]

    if dialectic.objection_ledger:
        parts += ["", "## Objections to Address", ""]
        for obj in dialectic.objection_ledger:
            parts.append(
                f"- [{obj.severity:.1f}] {obj.objection}"
            )

    return "\n".join(parts)


def _parse_response(
    content: str, *, domain: str | None = None
) -> ExecutionArtifact:
    """Parse model response into an ExecutionArtifact."""
    patches: list[str] = []
    test_results: list[str] = []
    created_files: list[str] = []
    tool_log: list[str] = []
    uncertainties: list[str] = []

    # Extract file references (code adapter pattern)
    import re
    file_pattern = re.compile(r"FILE:\s*(\S+)", re.MULTILINE)
    for m in file_pattern.finditer(content):
        created_files.append(m.group(1))

    # Extract test results
    test_pattern = re.compile(
        r"(?:test|tests?)\s*(?:passed|failed|pass|fail)[^.]*\.",
        re.IGNORECASE,
    )
    for m in test_pattern.finditer(content):
        test_results.append(m.group(0).strip())

    # Extract uncertainties
    uncertainty_patterns = [
        r"(?:uncertain|unclear|unknown|ambiguous)[^.]*\.",
        r"(?:may|might|could be)[^.]*\.",
    ]
    for pat in uncertainty_patterns:
        for m in re.finditer(pat, content, re.IGNORECASE):
            uncertainties.append(m.group(0).strip())

    # Extract tool usage mentions
    tool_pattern = re.compile(
        r"(?:used|ran|executed|called)\s+\w+\s+to\s+[^.]*\.",
        re.IGNORECASE,
    )
    for m in tool_pattern.finditer(content):
        tool_log.append(m.group(0).strip())

    return ExecutionArtifact(
        summary=content[:500] if len(content) > 500 else content,
        output_text=content,
        patches=patches,
        test_results=test_results,
        created_files=created_files,
        tool_log=tool_log,
        declared_uncertainties=uncertainties,
        structured_output={},
        status="completed",
    )


# Attach helpers to the base class as static-method-like utilities
# so adapters can call them easily.
# We monkey-patch them onto the concrete classes for convenience.

for _cls in [GenericAdapter, CodeAdapter, ResearchAdapter, WritingAdapter, ExperimentAdapter, AnalysisAdapter]:
    _cls._build_user_prompt = staticmethod(_build_user_prompt)  # type: ignore[attr-defined]
    _cls._parse_response = staticmethod(_parse_response)  # type: ignore[attr-defined]
