---
name: run
description: Use the local Autodialectics MCP server and CLI to compile tasks, execute anti-slop runs, inspect artifacts, replay runs, benchmark policies, and evolve champions in this repository.
---

# Autodialectics

Use this skill when the user wants to work through the Autodialectics harness instead of asking the model to freestyle a task.

Repository facts:
- Repo root: `/home/hmbown/Projects/autodialectics`
- Primary config: `autodialectics.yaml`
- MCP entrypoint: `uv run autodialectics-mcp`
- CLI entrypoint: `uv run autodialectics`
- Python fallback: `.venv/bin/python -m autodialectics.cli.main`

Preferred MCP workflow:

1. `health`
2. `init_runtime`
3. `compile_task`
4. `run_task`
5. `inspect_run` or `read_artifact`
6. `benchmark`, `evolve_policy`, `promote_policy`, `rollback_policy`, or `replay_run`

CLI fallback command forms:

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

Working rules:
- Prefer the MCP server when it is available through the plugin.
- Run CLI commands from the repo root when the MCP server is unavailable.
- Prefer `uv run autodialectics ...` over ad hoc module invocation.
- Use `--config autodialectics.yaml` if config resolution looks ambiguous.
- When a run finishes, inspect the generated `artifacts/run_*` directory and summarize the gate decision, score, slop composite, and unresolved risks.
- For benchmark work, report aggregate results and call out canary failures explicitly.
- For policy work, do not promote a challenger unless the benchmark output supports it.

Expected examples:
- Compile before a risky run if the task contract seems underspecified.
- Use `inspect` after `run` or `benchmark` instead of guessing from stdout.
- Use `replay` when the user wants the same task rerun under another policy.
