---
name: run
description: Use the local Autodialectics MCP server and CLI in this repository to compile tasks, run the anti-slop pipeline, inspect stored runs, benchmark policies, and replay or evolve them.
---

# Autodialectics Run Skill

Use this skill when the user wants the repository's own anti-slop harness to drive the work.

Repository facts:
- Root: the repository root for the active checkout
- Config: `autodialectics.yaml`
- Preferred MCP entrypoint: `uv run autodialectics-mcp`
- Preferred CLI command: `uv run autodialectics`

Preferred MCP workflow:

1. `health`
2. `init_runtime`
3. `compile_task`
4. `run_task`
5. `inspect_run` or `read_artifact`
6. `benchmark`, `evolve_policy`, `promote_policy`, `rollback_policy`, or `replay_run`

CLI fallback commands:

```bash
uv run autodialectics init
uv run autodialectics compile examples/code_fix/task.json
uv run autodialectics run examples/code_fix/task.json
uv run autodialectics benchmark
uv run autodialectics inspect <run_id>
uv run autodialectics replay <run_id>
uv run autodialectics evolve
uv run autodialectics promote <policy_id>
uv run autodialectics rollback
```

Usage guidance:
- Prefer the MCP tools when the plugin has loaded them.
- Work from the repository root for CLI fallback.
- Prefer compile plus inspect when a task or benchmark result is ambiguous.
- Summaries should include the run ID, decision, overall score, slop composite, and any unresolved risks.
- Do not claim a policy is better without benchmark evidence.

Arguments:
- If the user passes a task path after `/autodialectics:run`, treat it as the target task file and execute the narrowest fitting workflow.
