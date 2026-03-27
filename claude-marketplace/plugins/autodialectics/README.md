# Autodialectics Claude Plugin

This directory is a real Claude Code plugin packaged inside a local marketplace.

It includes:
- a plugin manifest
- a repo-local `.mcp.json` for `autodialectics-mcp`
- a reusable skill for the Autodialectics workflow
- the shared `autodialectics` MCP server entry

Local test flow:

```bash
claude --plugin-dir ./claude-marketplace/plugins/autodialectics
```

Marketplace install flow:

```text
/plugin marketplace add ./claude-marketplace
/plugin install autodialectics@autodialectics-marketplace
```

Primary skill:
- `/autodialectics:run`
