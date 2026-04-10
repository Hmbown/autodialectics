from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from autodialectics.integrations import mcp_server
from autodialectics.integrations.mcp_server import _ensure_within, _load_submission


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_mcp_server_lists_tools_and_compiles_task() -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "autodialectics-mcp"],
        cwd=REPO_ROOT,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "health" in tool_names
            assert "compile_task" in tool_names

            health = await session.call_tool("health")
            assert health.structuredContent["status"] == "ok"

            compile_result = await session.call_tool(
                "compile_task",
                {
                    "task_file": str(REPO_ROOT / "examples" / "code_fix" / "task.json"),
                },
            )
            assert compile_result.structuredContent["title"]
            assert compile_result.structuredContent["domain"] == "code"


def test_load_submission_rejects_paths_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)

    outside = tmp_path / "task.json"
    outside.write_text('{"title":"Outside","description":"Nope"}', encoding="utf-8")

    with pytest.raises(ValueError, match="Path must stay within one of"):
        _load_submission(str(outside))


def test_ensure_within_accepts_artifacts_subpath(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    artifact_file = artifact_root / "run_1" / "summary.md"
    artifact_file.parent.mkdir()
    artifact_file.write_text("ok", encoding="utf-8")

    assert _ensure_within(artifact_file.resolve(), artifact_root) == artifact_file.resolve()


def test_run_task_detach_returns_immediate_pollable_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyStore:
        def __init__(self) -> None:
            self.manifests: dict[str, dict[str, str]] = {}

        def get_run_manifest(self, run_id: str) -> dict[str, str] | None:
            return self.manifests.get(run_id)

        def get_artifact_paths(self, run_id: str) -> dict[str, str]:
            return {"submission.json": f"artifacts/{run_id}/submission.json"}

    store = DummyStore()

    class DummyRuntime:
        def __init__(self) -> None:
            self.store = store

        def run(self, submission, policy_id=None, run_id=None):
            assert run_id == "run_20260409050000_1234"
            store.manifests[run_id] = {
                "run_id": run_id,
                "status": "running",
                "policy_id": policy_id or "policy_default",
            }
            return SimpleNamespace(run_id=run_id)

    monkeypatch.setattr(mcp_server, "_load_runtime", lambda config_path=None: DummyRuntime())
    monkeypatch.setattr(mcp_server, "_load_submission", lambda task_file: SimpleNamespace(title="Task"))
    monkeypatch.setattr(mcp_server, "_build_run_id", lambda: "run_20260409050000_1234")
    monkeypatch.chdir(REPO_ROOT)

    payload = mcp_server.run_task(
        str(REPO_ROOT / "examples" / "code_fix" / "task.json"),
        policy_id="policy_test",
        detach=True,
    )

    assert payload["run_id"] == "run_20260409050000_1234"
    assert payload["status"] == "running"
    assert payload["background"] is True
    assert "inspect_run" in payload["inspect_hint"]
    assert payload["artifact_paths"]["submission.json"].endswith("submission.json")
