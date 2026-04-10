# Autodialectics

A structured pipeline for LLM task execution. Each run goes through contract compilation, evidence gathering, dialectical planning, domain execution, independent verification, slop scoring, and policy evolution.

## Pipeline

```text
Task JSON → Contract Compiler → Evidence Explorer → Dialectical Planner
                                                        ↓
                                     Thesis → Antithesis → Synthesis
                                                        ↓
                                               Domain Execution
                                                        ↓
                                        Independent Verification
                                                        ↓
                                        Slop Scoring & Evaluation
                                                        ↓
                                              Gate Decision
                                           (accept / reject /
                                            revise / rollback)
                                                        ↓
                                      Champion/Challenger Evolution
```

1. **Contract** — Locks the task into an immutable contract: objectives, deliverables, acceptance criteria, forbidden shortcuts.
2. **Evidence** — Loads attached assets and builds an evidence bundle via heuristic scoring or DSPy retrieval.
3. **Dialectic** — Generates a thesis plan, challenges it with an antithesis, and resolves into a synthesis.
4. **Execution** — Runs the plan through a domain adapter (code, research, writing, experiment, analysis, or generic).
5. **Verification** — Evaluates output against the contract independently.
6. **Evaluation** — Scores slop dimensions: unsupported claims, fake completion, requirement drift, benchmark gaming, redundancy.
7. **Gate** — Accepts, rejects, revises, or rolls back based on scores and evidence.
8. **Evolution** — Creates challenger policies from benchmark data; promotes only when they outperform the champion without increasing slop.

## Install

```bash
git clone https://github.com/Hmbown/autodialectics.git
cd autodialectics
pip install uv
uv sync
```

Optional:

```bash
uv sync --extra dev    # pytest
uv sync --extra dspy   # DSPy RLM + GEPA
```

## Quick start

```bash
uv run autodialectics init
uv run autodialectics compile examples/code_fix/task.json
uv run autodialectics run examples/code_fix/task.json
uv run autodialectics inspect <run_id>
uv run autodialectics replay <run_id>
uv run autodialectics benchmark
uv run autodialectics evolve
```

## Task format

Only `title` is required. Everything else has defaults.

```json
{
  "title": "Fix calculator division by zero",
  "description": "The calculator.py divide function crashes on zero input.",
  "domain": "code",
  "objectives": ["Handle division by zero gracefully"],
  "constraints": ["Do not change the function signature"],
  "deliverables": ["Patched calculator.py"],
  "acceptance_criteria": ["All tests pass"],
  "forbidden_shortcuts": ["Removing the divide function"],
  "workspace_root": "examples/code_fix/workspace",
  "verification_commands": ["python -m pytest -q test_calculator.py"],
  "max_repair_attempts": 3,
  "assets": [
    {
      "kind": "file",
      "location": "examples/code_fix/workspace/calculator.py",
      "label": "calculator.py"
    }
  ]
}
```

Domains: `code`, `research`, `writing`, `experiment`, `analysis`, `generic`.

Examples under `examples/`: `code_fix`, `research_synth`, `writing_revision`, `experiment_loop`, `self_review`.

## Code tasks

For code tasks that edit and verify a real repository:

- `workspace_root` — copied into an isolated sandbox for execution and verification
- `verification_commands` — explicit commands run against the sandbox (preferred over heuristic discovery)
- `max_repair_attempts` — bounded fix-verify-repair loop instead of single-shot
- `assets` — evidence for planning, separate from the workspace

The code adapter copies the workspace, snapshots it into the executor prompt, runs verification, and retries with failure feedback up to the repair budget.

## Configuration

Resolved in order:

1. `--config PATH`
2. `AUTODIALECTICS_CONFIG`
3. `./autodialectics.yaml`
4. `~/.config/autodialectics/autodialectics.yaml`

```yaml
cliproxy_base_url: "http://127.0.0.1:8642"
cliproxy_api_key: ""
cliproxy_model: "default"
db_path: "autodialectics.db"
artifacts_dir: "artifacts"
benchmark_dir: "benchmarks/cases"
use_dspy_rlm: false
```

The model client speaks OpenAI-compatible `/v1/chat/completions`. Point `cliproxy_base_url` at any compatible endpoint.

## Claude Code plugin

Install as a distributable Claude Code plugin:

```bash
pip install autodialectics
claude plugin install autodialectics@autodialectics-marketplace
```

Skills: `/autodialectics:run`, `/autodialectics:inspect`, `/autodialectics:benchmark`, `/autodialectics:replay`

Subagent: `@autodialectics:dialectical-reviewer` — structured read-only review of pipeline runs.

Or test locally: `claude --plugin-dir ./claude-marketplace/plugins/autodialectics`

See [`claude-marketplace/plugins/autodialectics/README.md`](claude-marketplace/plugins/autodialectics/README.md) for details.

## MCP server

All integrations share the same MCP backend:

```bash
uv run autodialectics-mcp
```

11 tools: `health`, `init_runtime`, `compile_task`, `run_task`, `benchmark`, `inspect_run`, `read_artifact`, `evolve_policy`, `promote_policy`, `rollback_policy`, `replay_run`.

Root `.mcp.json` configures it for Claude Code. Codex and OpenCode integrations are under `plugins/` and `.opencode/` respectively.

## CLI gateways

Local gateways that expose CLI tools as OpenAI-compatible endpoints:

```bash
uv run claude-gateway
uv run codex-gateway
uv run cli-gateway    # auto-detects; override with CLI_GATEWAY_PROVIDER=codex|claude|hermes
```

## REST API

```bash
uv run autodialectics serve --host 0.0.0.0 --port 8000 --reload
```

Endpoints: `GET /health`, `POST /tasks/compile`, `POST /runs`, `GET /runs/{run_id}`, `POST /benchmarks/run`, `POST /policies/evolve`, `POST /policies/{policy_id}/promote`, `POST /policies/rollback`.

## DSPy

Two optional paths when DSPy is installed:

- **RLM** — recursive language-model exploration for evidence retrieval
- **GEPA** — prompt evolution for challenger policy optimization

Falls back to heuristics automatically if unavailable.

## Testing

```bash
uv run pytest -q
uv run pytest tests/test_integrations.py -m integration -q  # requires live endpoint
```

## Project layout

```text
autodialectics/
├── autodialectics/        # core package
│   ├── api/               # FastAPI REST endpoints
│   ├── cli/               # Typer CLI
│   ├── contract/          # contract compiler
│   ├── dialectic/         # thesis/antithesis/synthesis planner
│   ├── evaluation/        # slop scoring + pre-mortem router
│   ├── evolution/         # champion/challenger policy management
│   ├── execution/         # domain adapters (code, research, etc.)
│   ├── exploration/       # evidence gathering
│   ├── integrations/      # MCP server
│   ├── memory/            # context management
│   ├── routing/           # model client + CLI gateways
│   ├── schemas/           # Pydantic models
│   ├── storage/           # SQLite + artifact persistence
│   └── utils/
├── benchmarks/            # benchmark cases
├── claude-marketplace/    # Claude Code plugin
├── examples/              # example tasks
├── plugins/               # Codex plugin
├── tests/
└── docs/
```

## License

MIT
