"""Domain-specific execution adapters and registry."""

from __future__ import annotations

import difflib
import logging
import shlex
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

from autodialectics.routing.cliproxy import (
    is_offline_response_text,
    is_request_failure_response_text,
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
            "response. Do not stub or skip functionality. Return only the final "
            "implementation payload, not your working notes. If the current "
            "workspace already satisfies the task, respond with NO_CHANGES_NEEDED "
            "on the first line followed by a brief justification."
        )
        with tempfile.TemporaryDirectory(prefix="autodialectics-code-") as tmpdir:
            sandbox_root = Path(tmpdir) / "workspace"
            sandbox_root.mkdir(parents=True, exist_ok=True)
            copied_assets = _materialize_workspace(contract, sandbox_root)

            base_user = self._build_user_prompt(contract, evidence, dialectic)
            base_user += (
                "\n\nIMPORTANT: Output all code changes clearly. "
                "For each file, use the format:\n"
                "FILE: path/to/file.py\n```python\n<code>\n```\n"
                "Use repository-relative paths only. Do not describe a patch without "
                "including the full replacement content for each changed file. "
                "If no code change is required, do not emit FILE blocks."
            )
            if contract.workspace_root:
                base_user += (
                    "\n\n## Sandbox Workspace\n\n"
                    f"- Use `{contract.workspace_root}` as the repository root inside the sandbox."
                )
            if contract.verification_commands:
                base_user += "\n\n## Required Verification Commands\n\n"
                for command in contract.verification_commands:
                    base_user += f"- `{command}`\n"

            workspace_context = _render_workspace_context(sandbox_root)
            if workspace_context:
                base_user += "\n\n## Workspace Context\n\n" + workspace_context

            max_attempts = max(contract.max_repair_attempts, 1)
            candidate_files: dict[str, str] = {}
            attempt_summaries: list[dict[str, Any]] = []
            repair_context = ""

            for attempt in range(1, max_attempts + 1):
                user = base_user
                if repair_context:
                    user += "\n\n" + repair_context

                resp = model_client.complete(
                    role="executor",
                    system_prompt=system,
                    user_prompt=user,
                )
                execution = self._parse_response(resp.content, domain="code")
                new_blocks = _extract_file_blocks(resp.content)
                if new_blocks:
                    candidate_files.update(new_blocks)
                else:
                    execution.tool_log.append(
                        "Executor response did not include FILE blocks; verifying copied workspace without modifications."
                    )

                execution = _apply_code_changes_in_sandbox(
                    contract=contract,
                    execution=execution,
                    file_blocks=candidate_files,
                    workspace_root=sandbox_root,
                    copied_assets=copied_assets,
                )
                execution.tool_log.append(f"Repair attempt {attempt}/{max_attempts}.")

                sandbox = execution.structured_output.get("sandbox", {})
                attempt_summaries.append(
                    {
                        "attempt": attempt,
                        "status": execution.status,
                        "applied_files": list(sandbox.get("applied_files", [])),
                        "test_command": sandbox.get("test_command"),
                        "test_exit_code": sandbox.get("test_exit_code"),
                    }
                )
                execution.structured_output["attempts"] = list(attempt_summaries)

                if (
                    execution.status == "completed"
                    or attempt == max_attempts
                    or execution.structured_output.get("llm_request_failed")
                    or execution.structured_output.get("offline_mode")
                ):
                    return execution

                repair_context = _build_code_repair_context(
                    execution=execution,
                    candidate_files=candidate_files,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )

        return ExecutionArtifact(
            summary="Code execution did not produce a usable attempt.",
            output_text="Code execution did not produce a usable attempt.",
            status="failed",
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
            "Acknowledge contradictory evidence. Output only the final "
            "deliverable; do not narrate your process or restate the prompt.\n\n"
            "Structure your response with:\n"
            "## Claims and Evidence\n"
            "For each claim: [CLAIM] - Evidence: [source/reasoning]\n\n"
            "## Inferences\n"
            "For each inference: [INFERENCE] - Based on: [evidence]\n\n"
            "## Contradictions and Debates\n"
            "Summarize the strongest direct disagreement, contested interpretation, "
            "or mixed evidence in the sources. If none exists, say that explicitly.\n\n"
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
            "Every paragraph should advance the document's purpose. Output "
            "only the final revised document and the requested change summary; "
            "do not narrate your process or echo the prompt.\n\n"
            "Output the complete revised document. End with a summary "
            "of substantive changes made."
        )
        user = self._build_user_prompt(contract, evidence, dialectic)
        source_assets = _load_textual_assets_for_prompt(contract)
        if source_assets:
            user += "\n\n## Source Material\n\n" + source_assets
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
            "Do not fabricate data. If reporting results, include actual data. "
            "Output only the final protocol or analysis, not intermediate reasoning."
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
            "Tie all conclusions to specific evidence. Output only the final "
            "memo; do not narrate your process or restate the prompt.\n\n"
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


def _stable_mount_name(root: Path, used_names: set[str]) -> str:
    """Return a deterministic mount name for a copied root without collisions."""
    candidates = [root.name]

    parent = root.parent
    if parent.name:
        candidates.append(f"{parent.name}__{root.name}")

    grandparent = parent.parent
    if parent.name and grandparent.name:
        candidates.append(f"{grandparent.name}__{parent.name}__{root.name}")

    for candidate in candidates:
        if candidate and candidate not in used_names:
            used_names.add(candidate)
            return candidate

    suffix = abs(hash(str(root.resolve()))) % 100000
    fallback = f"{root.name or 'root'}__{suffix:05d}"
    while fallback in used_names:
        suffix += 1
        fallback = f"{root.name or 'root'}__{suffix:05d}"
    used_names.add(fallback)
    return fallback


def _materialize_workspace(
    source: TaskContract | list[Any],
    workspace_root: Path,
) -> list[str]:
    """Copy code assets or an explicit workspace into an isolated sandbox."""
    from autodialectics.schemas import AssetKind

    contract = source if isinstance(source, TaskContract) else None
    assets = contract.relevant_assets if contract is not None else source

    if contract is not None and contract.workspace_root:
        root = Path(contract.workspace_root).expanduser().resolve()
        if root.is_dir():
            _copy_tree_contents(root, workspace_root)
            return [root.name or "."]

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

    used_mounts: set[str] = set()
    for root in unique_roots:
        mount_name = _stable_mount_name(root, used_mounts)
        target = workspace_root / mount_name
        shutil.copytree(root, target, dirs_exist_ok=True)
        copied.append(mount_name)

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


def _load_textual_assets_for_prompt(
    contract: TaskContract,
    *,
    max_assets: int = 3,
    max_chars_per_asset: int = 12000,
) -> str:
    """Load small textual assets directly into prompts for revision-style tasks."""
    from autodialectics.schemas import AssetKind

    rendered: list[str] = []
    for asset in contract.relevant_assets[:max_assets]:
        text = ""
        label = asset.label or asset.asset_id

        if asset.kind == AssetKind.INLINE_TEXT and asset.text:
            text = asset.text
        elif asset.kind == AssetKind.JSON:
            text = asset.text or ""
        elif asset.kind == AssetKind.FILE and asset.location:
            path = Path(asset.location)
            if path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    text = ""

        if not text:
            continue

        snippet = text[:max_chars_per_asset]
        rendered.append(f"[{label}]\n{snippet}")

    return "\n\n".join(rendered)


def _render_workspace_context(
    workspace_root: Path,
    *,
    max_entries: int = 60,
) -> str:
    """Render a compact file listing for the sandbox workspace."""
    entries = sorted(
        path.relative_to(workspace_root).as_posix()
        for path in workspace_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    if not entries:
        return ""

    preview = entries[:max_entries]
    rendered = [f"- {entry}" for entry in preview]
    if len(entries) > max_entries:
        rendered.append(f"- ... ({len(entries) - max_entries} more files)")
    return "\n".join(rendered)


def _command_display(command: str | list[str]) -> str:
    """Render a command for logs and summaries."""
    if isinstance(command, str):
        return command
    return shlex.join(command)


def _select_verification_commands(
    workspace_root: Path,
    changed_files: list[str],
    explicit_commands: list[str],
) -> tuple[list[str | list[str]], list[str]]:
    """Choose the verification commands for the sandbox."""
    normalized_explicit = [command.strip() for command in explicit_commands if command.strip()]
    if normalized_explicit:
        return normalized_explicit, []

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
        return [[sys.executable, "-m", "pytest", "-q", *targets]], targets

    python_targets = [path for path in changed_files if path.endswith(".py")]
    if python_targets:
        return [[sys.executable, "-m", "py_compile", *python_targets]], python_targets

    return [], []


def _run_verification_commands(
    commands: list[str | list[str]],
    *,
    workspace_root: Path,
) -> tuple[int | None, str, str, list[dict[str, Any]]]:
    """Execute verification commands inside the sandbox workspace."""
    if not commands:
        return None, "", "", []

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    history: list[dict[str, Any]] = []
    final_exit_code: int | None = None

    for command in commands:
        completed = subprocess.run(
            command,
            cwd=workspace_root,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
            shell=isinstance(command, str),
        )
        command_text = _command_display(command)
        history.append(
            {
                "command": command_text,
                "exit_code": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
        if completed.stdout.strip():
            stdout_parts.append(f"$ {command_text}\n{completed.stdout.strip()}")
        if completed.stderr.strip():
            stderr_parts.append(f"$ {command_text}\n{completed.stderr.strip()}")
        final_exit_code = completed.returncode
        if completed.returncode != 0:
            break

    return (
        final_exit_code,
        "\n\n".join(stdout_parts),
        "\n\n".join(stderr_parts),
        history,
    )


def _render_candidate_files(
    candidate_files: dict[str, str],
    *,
    max_files: int = 4,
    max_chars_per_file: int = 4000,
) -> str:
    """Render the current candidate file set for repair prompts."""
    rendered: list[str] = []
    for rel_path, content in list(candidate_files.items())[:max_files]:
        snippet = content[:max_chars_per_file]
        rendered.append(
            f"FILE: {rel_path}\n```text\n{snippet}\n```"
        )
    return "\n\n".join(rendered)


def _render_workspace_context(
    workspace_root: Path,
    *,
    max_files: int = 6,
    max_chars_per_file: int = 3000,
    max_tree_entries: int = 80,
) -> str:
    """Render a compact workspace tree plus representative file contents."""
    all_files = [
        path
        for path in sorted(workspace_root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]
    if not all_files:
        return ""

    tree_entries = [
        path.relative_to(workspace_root).as_posix()
        for path in all_files[:max_tree_entries]
    ]
    preferred_suffixes = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".md",
        ".txt",
        ".go",
        ".rs",
        ".swift",
    }
    ranked_files = sorted(
        all_files,
        key=lambda path: (
            path.suffix not in preferred_suffixes,
            "test" not in path.name.lower(),
            len(path.relative_to(workspace_root).parts),
            path.relative_to(workspace_root).as_posix(),
        ),
    )

    rendered_files: list[str] = []
    for path in ranked_files[:max_files]:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        rel_path = path.relative_to(workspace_root).as_posix()
        rendered_files.append(
            f"[{rel_path}]\n```text\n{content[:max_chars_per_file]}\n```"
        )

    if not rendered_files:
        return ""

    parts = [
        "### Workspace Tree",
        "",
        "```text",
        *tree_entries,
        "```",
        "",
        "### Representative Files",
        "",
        "\n\n".join(rendered_files),
    ]
    return "\n".join(parts)


def _build_code_repair_context(
    *,
    execution: ExecutionArtifact,
    candidate_files: dict[str, str],
    attempt: int,
    max_attempts: int,
) -> str:
    """Build follow-up context for a failed code attempt."""
    sandbox = execution.structured_output.get("sandbox", {})
    command_text = sandbox.get("test_command") or "none"
    exit_code = sandbox.get("test_exit_code")
    stdout = str(sandbox.get("stdout", "")).strip()
    stderr = str(sandbox.get("stderr", "")).strip()

    parts = [
        f"## Previous Attempt Failed ({attempt}/{max_attempts})",
        "",
        f"- Verification command(s): `{command_text}`",
        f"- Exit code: `{exit_code}`",
    ]
    if stdout:
        parts += ["", "### Verification Stdout", "", f"```text\n{stdout[:4000]}\n```"]
    if stderr:
        parts += ["", "### Verification Stderr", "", f"```text\n{stderr[:4000]}\n```"]
    if candidate_files:
        parts += [
            "",
            "### Current Candidate Files",
            "",
            _render_candidate_files(candidate_files),
            "",
            "Revise the existing candidate files as needed. You may emit only the files that changed from the current candidate state.",
        ]
    return "\n".join(parts)


def _apply_code_changes_in_sandbox(
    *,
    contract: TaskContract,
    execution: ExecutionArtifact,
    file_blocks: dict[str, str],
    workspace_root: Path | None = None,
    copied_assets: list[str] | None = None,
) -> ExecutionArtifact:
    """Materialize a sandbox workspace, apply model changes, and run verification."""
    owns_workspace = workspace_root is None
    with tempfile.TemporaryDirectory(prefix="autodialectics-code-") as tmpdir:
        active_workspace = workspace_root or (Path(tmpdir) / "workspace")
        if owns_workspace:
            active_workspace.mkdir(parents=True, exist_ok=True)
            copied_assets = _materialize_workspace(contract, active_workspace)

        patches: list[str] = []
        applied_files: list[str] = []
        llm_request_failed = bool(execution.structured_output.get("llm_request_failed"))
        offline_mode = bool(execution.structured_output.get("offline_mode"))
        no_changes_declared = bool(execution.structured_output.get("no_changes_declared"))
        for rel_path, new_content in file_blocks.items():
            target = _safe_workspace_path(active_workspace, rel_path)
            before = target.read_text(encoding="utf-8") if target.exists() else ""
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(new_content, encoding="utf-8")
            patch_text = _build_patch(rel_path, before, new_content)
            if patch_text:
                patches.append(patch_text)
            applied_files.append(rel_path)

        protocol_violation = not applied_files and not no_changes_declared
        if protocol_violation and not llm_request_failed and not offline_mode:
            execution.tool_log.append(
                "Executor did not return FILE blocks or an explicit NO_CHANGES_NEEDED response."
            )

        commands, verification_targets = _select_verification_commands(
            active_workspace,
            applied_files,
            contract.verification_commands,
        )
        exit_code, stdout, stderr, verification_runs = _run_verification_commands(
            commands,
            workspace_root=active_workspace,
        )

        execution.created_files = applied_files
        execution.patches = patches
        execution.test_results = []
        if commands:
            command_text = " && ".join(_command_display(command) for command in commands)
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

        status_ok = exit_code in (None, 0)
        if llm_request_failed or offline_mode or protocol_violation:
            status_ok = False

        execution.status = "completed" if status_ok else "failed"
        execution.structured_output = {
            **execution.structured_output,
            "sandbox": {
                "applied": bool(file_blocks),
                "no_op_verification": not file_blocks,
                "no_changes_declared": no_changes_declared,
                "copied_assets": copied_assets or [],
                "applied_files": applied_files,
                "verification_targets": verification_targets,
                "verification_runs": verification_runs,
                "test_command": command_text,
                "test_exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "protocol_violation": protocol_violation,
            }
        }

        report_lines = [
            "",
            "SANDBOX REPORT",
            f"Applied files: {', '.join(applied_files) if applied_files else '(none)'}",
            f"Verification command: {command_text or 'none'}",
            f"Verification exit code: {exit_code if exit_code is not None else 'n/a'}",
        ]
        if protocol_violation:
            report_lines.append(
                "Protocol violation: executor returned neither FILE blocks nor NO_CHANGES_NEEDED."
            )
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
    if is_request_failure_response_text(content):
        return ExecutionArtifact(
            summary=content,
            output_text=content,
            tool_log=["Executor request failed before producing a usable response."],
            declared_uncertainties=[
                "Configured LLM endpoint request failed; execution artifact may be incomplete."
            ],
            structured_output={"llm_request_failed": True, "domain": domain or "generic"},
            status="failed",
        )
    if is_offline_response_text(content):
        return ExecutionArtifact(
            summary=content,
            output_text=content,
            tool_log=["Executor ran in offline mode and did not produce a usable response."],
            declared_uncertainties=[
                "No live LLM endpoint was configured; execution artifact may be incomplete."
            ],
            structured_output={"offline_mode": True, "domain": domain or "generic"},
            status="failed",
        )

    patches: list[str] = []
    test_results: list[str] = []
    created_files: list[str] = []
    tool_log: list[str] = []
    uncertainties: list[str] = []
    no_changes_declared = content.lstrip().startswith("NO_CHANGES_NEEDED")

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
        structured_output={
            "no_changes_declared": no_changes_declared,
            "domain": domain or "generic",
        },
        status="completed",
    )


# Attach helpers to the base class as static-method-like utilities
# so adapters can call them easily.
# We monkey-patch them onto the concrete classes for convenience.

for _cls in [GenericAdapter, CodeAdapter, ResearchAdapter, WritingAdapter, ExperimentAdapter, AnalysisAdapter]:
    _cls._build_user_prompt = staticmethod(_build_user_prompt)  # type: ignore[attr-defined]
    _cls._parse_response = staticmethod(_parse_response)  # type: ignore[attr-defined]
