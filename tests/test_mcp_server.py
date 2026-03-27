from __future__ import annotations

from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

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
