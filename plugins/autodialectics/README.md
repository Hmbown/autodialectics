# Autodialectics Codex Plugin

This repo-local Codex plugin wraps the existing Autodialectics runtime as a reusable skill package plus a local MCP server.

Installed surface:
- Skill: `autodialectics:run`
- MCP server: `autodialectics`

Repository wiring:
- Plugin manifest: `.codex-plugin/plugin.json`
- MCP config: `.mcp.json`
- Skill entrypoint: `skills/run/SKILL.md`
- Marketplace entry: `.agents/plugins/marketplace.json`

The plugin intentionally keeps the Python package as the system of record. It does not fork or reimplement the runtime.
