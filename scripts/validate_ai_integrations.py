from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Missing required file: {path}")


def main() -> None:
    required_files = [
        ROOT / ".agents/plugins/marketplace.json",
        ROOT / "plugins/autodialectics/.codex-plugin/plugin.json",
        ROOT / "plugins/autodialectics/.mcp.json",
        ROOT / "plugins/autodialectics/skills/run/SKILL.md",
        ROOT / "claude-marketplace/.claude-plugin/marketplace.json",
        ROOT / "claude-marketplace/plugins/autodialectics/.claude-plugin/plugin.json",
        ROOT / "claude-marketplace/plugins/autodialectics/.mcp.json",
        ROOT / "claude-marketplace/plugins/autodialectics/skills/run/SKILL.md",
        ROOT / "opencode.json",
        ROOT / ".opencode/plugins/autodialectics.js",
        ROOT / ".opencode/commands/autodialectics-run.md",
        ROOT / ".opencode/commands/autodialectics-benchmark.md",
        ROOT / ".opencode/agents/autodialectics-review.md",
        ROOT / "docs/ai-plugin-integrations.md",
        ROOT / "test.md",
    ]
    for path in required_files:
        require_file(path)

    codex_marketplace = load_json(ROOT / ".agents/plugins/marketplace.json")
    if not codex_marketplace.get("plugins"):
        raise ValueError("Codex marketplace has no plugin entries")

    codex_entry = codex_marketplace["plugins"][0]
    codex_source = codex_entry["source"]["path"]
    require_file(ROOT / codex_source.lstrip("./") / ".codex-plugin/plugin.json")

    codex_plugin = load_json(ROOT / "plugins/autodialectics/.codex-plugin/plugin.json")
    if codex_plugin["name"] != "autodialectics":
        raise ValueError("Codex plugin manifest name mismatch")
    if codex_plugin.get("mcpServers") != "./.mcp.json":
        raise ValueError("Codex plugin manifest is not wired to .mcp.json")
    codex_mcp = load_json(ROOT / "plugins/autodialectics/.mcp.json")
    if "autodialectics" not in codex_mcp.get("mcpServers", {}):
        raise ValueError("Codex MCP config missing autodialectics server")

    claude_marketplace = load_json(ROOT / "claude-marketplace/.claude-plugin/marketplace.json")
    if not claude_marketplace.get("plugins"):
        raise ValueError("Claude marketplace has no plugin entries")

    claude_entry = claude_marketplace["plugins"][0]
    claude_source = claude_entry["source"]
    require_file(
        ROOT / "claude-marketplace" / claude_source.lstrip("./") / ".claude-plugin/plugin.json"
    )

    claude_plugin = load_json(
        ROOT / "claude-marketplace/plugins/autodialectics/.claude-plugin/plugin.json"
    )
    if claude_plugin["name"] != "autodialectics":
        raise ValueError("Claude plugin manifest name mismatch")
    claude_mcp = load_json(ROOT / "claude-marketplace/plugins/autodialectics/.mcp.json")
    if "autodialectics" not in claude_mcp.get("mcpServers", {}):
        raise ValueError("Claude MCP config missing autodialectics server")

    opencode_config = load_json(ROOT / "opencode.json")
    opencode_server = opencode_config.get("mcp", {}).get("autodialectics")
    if not opencode_server:
        raise ValueError("OpenCode config missing autodialectics MCP entry")
    if opencode_server.get("type") != "local":
        raise ValueError("OpenCode autodialectics MCP entry must use type=local")

    print("AI integration layout looks valid.")


if __name__ == "__main__":
    main()
