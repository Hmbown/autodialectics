---
description: Compile or run a local Autodialectics task from this repository
agent: build
---

Use the Autodialectics harness in this repository instead of improvising the task.

Rules:
- Prefer the `autodialectics` MCP server when available.
- For CLI fallback, work from the repository root and use `uv run autodialectics`.
- Use `autodialectics.yaml` if config resolution is ambiguous.
- If `$ARGUMENTS` is empty, ask the user for a task file or choose a matching example only if the user clearly asked for a demo.

If the user provided a task path in `$ARGUMENTS`, decide whether you should:
1. compile it first with `compile_task` or `uv run autodialectics compile $ARGUMENTS`
2. run it with `run_task` or `uv run autodialectics run $ARGUMENTS`
3. inspect the resulting run artifacts with `inspect_run`/`read_artifact` or `uv run autodialectics inspect <run_id>`

Always report the run ID, decision, overall score, slop composite, and unresolved risks.
