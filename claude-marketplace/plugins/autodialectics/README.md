# Autodialectics Claude Code Plugin

Anti-slop harness for keeping LLMs on-task with contracts, evidence, dialectics, verification, and policy evolution.

## Install

1. Install the autodialectics package:

```bash
pip install autodialectics
# or
uv pip install autodialectics
```

2. Install the plugin:

```bash
claude plugin install autodialectics@autodialectics-marketplace
```

Or test locally during development:

```bash
claude --plugin-dir ./claude-marketplace/plugins/autodialectics
```

## Skills

| Skill | Description |
|-------|-------------|
| `/autodialectics:run` | Compile and execute the anti-slop pipeline for a task |
| `/autodialectics:inspect` | Examine run results, manifests, and artifacts |
| `/autodialectics:benchmark` | Run benchmark suites and manage policy evolution |
| `/autodialectics:replay` | Re-run a stored run with an optional policy override |

## Subagents

| Agent | Description |
|-------|-------------|
| `@autodialectics:dialectical-reviewer` | Structured review of pipeline runs — reads artifacts, interprets slop scores, compares policies |

## MCP Tools

The plugin exposes 11 tools via the `autodialectics` MCP server:

- `health` — check server reachability
- `init_runtime` — initialize database and default champion policy
- `compile_task` — compile task JSON into an immutable contract
- `run_task` — execute the full pipeline (supports `detach` for background runs)
- `benchmark` — run a benchmark suite
- `inspect_run` — retrieve run manifest and artifact paths
- `read_artifact` — read a specific artifact by name
- `evolve_policy` — create a challenger policy from benchmark data
- `promote_policy` — promote a challenger to champion
- `rollback_policy` — revert to the previous champion
- `replay_run` — re-execute a stored run with optional policy override

## Requirements

- Python >= 3.11
- `autodialectics` package installed and `autodialectics-mcp` on PATH
