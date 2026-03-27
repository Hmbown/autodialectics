# AI Integration Verification Prompt

Use this repository as the verification target:

- Repo root: `/home/hmbown/Projects/autodialectics`
- Goal: verify that the Codex, Claude Code, and OpenCode integrations are correctly packaged and usable

## What to verify

1. Repository layout
- Confirm these files exist and are internally consistent:
  - `.agents/plugins/marketplace.json`
  - `plugins/autodialectics/.codex-plugin/plugin.json`
  - `plugins/autodialectics/.mcp.json`
  - `plugins/autodialectics/skills/run/SKILL.md`
  - `claude-marketplace/.claude-plugin/marketplace.json`
  - `claude-marketplace/plugins/autodialectics/.claude-plugin/plugin.json`
  - `claude-marketplace/plugins/autodialectics/.mcp.json`
  - `claude-marketplace/plugins/autodialectics/skills/run/SKILL.md`
  - `opencode.json`
  - `.opencode/plugins/autodialectics.js`
  - `.opencode/commands/autodialectics-run.md`
  - `.opencode/commands/autodialectics-benchmark.md`
  - `.opencode/agents/autodialectics-review.md`
  - `docs/ai-plugin-integrations.md`
  - `tests/test_mcp_server.py`

2. Local validation
- Run:

```bash
cd /home/hmbown/Projects/autodialectics
python scripts/validate_ai_integrations.py
node --check .opencode/plugins/autodialectics.js
uv run autodialectics --help
uv run pytest tests/test_mcp_server.py -q
```

- Start a real stdio MCP session against `uv run autodialectics-mcp` and:
  - call `health`
  - call `compile_task` with `examples/code_fix/task.json`
  - report the returned title and domain

- If `claude` is installed, also run:

```bash
claude plugin validate ./claude-marketplace/plugins/autodialectics
claude plugin validate ./claude-marketplace
```

3. Semantic review
- Confirm the Codex plugin is a thin wrapper over the existing repo CLI instead of a reimplementation.
- Confirm the shared MCP server is the only backend implementation and the integrations stay thin.
- Confirm the Claude integration uses the official plugin layout and local marketplace layout.
- Confirm the OpenCode integration uses official project-level plugin, command, agent, and MCP config locations.
- Confirm the instructions point at the real repo commands:
  - `uv run autodialectics-mcp`
  - `uv run autodialectics compile ...`
  - `uv run autodialectics run ...`
  - `uv run autodialectics benchmark`
  - `uv run autodialectics inspect ...`

4. Report
- Report any broken paths, invalid JSON, invalid markdown frontmatter, or untestable assumptions.
- If something is wrong, propose the smallest fix that preserves the current structure.

## Constraints

- Do not rewrite the whole integration unless there is a concrete incompatibility.
- Prefer official behavior over guessed behavior.
- Keep the final report concrete and reference files directly.
