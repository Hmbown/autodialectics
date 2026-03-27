# AI Plugin Integrations

This repository now includes first-class integrations for Codex, Claude Code, and OpenCode, all backed by the same local Autodialectics MCP server.

## Shared backend

- Python entrypoint: `uv run autodialectics-mcp`
- Module: `autodialectics.integrations.mcp_server`
- Core tools:
  - `health`
  - `init_runtime`
  - `compile_task`
  - `run_task`
  - `benchmark`
  - `inspect_run`
  - `read_artifact`
  - `evolve_policy`
  - `promote_policy`
  - `rollback_policy`
  - `replay_run`

## Codex

Files:
- `.agents/plugins/marketplace.json`
- `plugins/autodialectics/.codex-plugin/plugin.json`
- `plugins/autodialectics/.mcp.json`
- `plugins/autodialectics/skills/run/SKILL.md`

Intent:
- Provide a repo-local Codex plugin that exposes the Autodialectics workflow as a reusable skill plus local MCP server.

Notes:
- The underlying system of record remains the Python package and CLI.
- The plugin is intentionally thin and delegates to `uv run autodialectics-mcp` and `uv run autodialectics ...`.

## Claude Code

Files:
- `claude-marketplace/.claude-plugin/marketplace.json`
- `claude-marketplace/plugins/autodialectics/.claude-plugin/plugin.json`
- `claude-marketplace/plugins/autodialectics/.mcp.json`
- `claude-marketplace/plugins/autodialectics/skills/run/SKILL.md`

Local development:

```bash
claude --plugin-dir ./claude-marketplace/plugins/autodialectics
```

Local marketplace flow:

```text
/plugin marketplace add ./claude-marketplace
/plugin install autodialectics@autodialectics-marketplace
```

Installed skill:
- `/autodialectics:run`

Installed MCP server:
- `autodialectics`

## OpenCode

Files:
- `opencode.json`
- `.opencode/plugins/autodialectics.js`
- `.opencode/commands/autodialectics-run.md`
- `.opencode/commands/autodialectics-benchmark.md`
- `.opencode/agents/autodialectics-review.md`

Intent:
- Project-local OpenCode plugin that injects repository environment variables for shell commands.
- Project-local OpenCode MCP configuration for the Autodialectics server.
- Companion commands for common Autodialectics workflows.
- A read-only review subagent for stored run analysis.

OpenCode surface:
- MCP server: `autodialectics`
- `/autodialectics-run`
- `/autodialectics-benchmark`
- `@autodialectics-review`

## Validation

Repository validation script:

```bash
python scripts/validate_ai_integrations.py
uv run pytest tests/test_mcp_server.py -q
```

Additional local checks:

```bash
node --check .opencode/plugins/autodialectics.js
uv run autodialectics --help
uv run pytest tests/test_mcp_server.py -q
claude plugin validate ./claude-marketplace/plugins/autodialectics
claude plugin validate ./claude-marketplace
```
