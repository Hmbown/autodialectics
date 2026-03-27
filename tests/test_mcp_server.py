from __future__ import annotations

from pathlib import Path

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


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
