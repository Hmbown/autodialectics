# Autodialectics

An agentic harness that keeps LLMs honest during research, code, and other high-drift work.

Instead of hoping a model stays on task, Autodialectics wraps every run in a structured pipeline: immutable contracts, evidence gathering, dialectical planning (thesis/antithesis/synthesis), domain-specific execution, independent verification, slop scoring, and champion/challenger policy evolution.

## Why

Most agent failures aren't intelligence failures. They're control failures:

- The task changes shape mid-run
- Evidence is thin but confidence stays high
- Objections get ignored
- The system claims "done" without doing the hard part
- Evaluation collapses into self-congratulation

Autodialectics is the harness around that behavior.

## How it works

```
Task JSON ──> Contract Compiler ──> Evidence Explorer ──> Dialectical Planner
                                                              │
                                          Thesis ──> Antithesis ──> Synthesis
                                                              │
                                                     Domain Execution
                                                              │
                                              Independent Verification
                                                              │
                                              Slop Scoring & Evaluation
                                                              │
                                                     Gate Decision
                                                   (accept / reject /
                                                    revise / rollback)
                                                              │
                                              Champion/Challenger Evolution
```

**1. Contract compilation** -- Lock the task into an immutable contract with objectives, deliverables, acceptance criteria, and forbidden shortcuts.

**2. Evidence exploration** -- Load attached assets and build an evidence bundle using heuristic chunk scoring or DSPy-assisted retrieval.

**3. Dialectical planning** -- Force the system through thesis, antithesis, and synthesis. The first plan never stands uncontested.

**4. Execution** -- Domain adapters handle code, research, writing, experiment, analysis, or generic tasks. Code tasks run in a workspace-copy sandbox with test verification.

**5. Verification** -- Evaluate output against the contract from a fresh perspective, independent from execution.

**6. Evaluation** -- Score slop dimensions: unsupported claims, fake completion, requirement drift, benchmark gaming, redundancy.

**7. Gate** -- Accept, reject, revise, or rollback based on evidence.

**8. Evolution** -- Create challenger policies from benchmark results. Promote only when a challenger outperforms the champion without increasing slop.

## Install

```bash
git clone https://github.com/Hmbown/autodialectics.git
cd autodialectics
pip install uv
uv sync
```

For development and testing:

```bash
uv sync --extra dev
```

For DSPy integration (optional):

```bash
uv sync --extra dspy
```

## Quick start

```bash
# Initialize the database and default champion policy
uv run autodialectics init

# Compile a task into an immutable contract (inspect before running)
uv run autodialectics compile examples/code_fix/task.json

# Run the full pipeline
uv run autodialectics run examples/code_fix/task.json

# Inspect a completed run
uv run autodialectics inspect <run_id>

# Run the benchmark suite
uv run autodialectics benchmark

# Evolve a challenger policy from benchmark evidence
uv run autodialectics evolve

# Promote a challenger that outperforms the champion
uv run autodialectics promote <policy_id>

# Rollback to the previous champion
uv run autodialectics rollback

# Replay a run under a different policy
uv run autodialectics replay <run_id>

# Start the REST API
uv run autodialectics serve --host 0.0.0.0 --port 8000
```

### Task format

Tasks are JSON files with a title, description, and optional attached assets:

```json
{
  "title": "Fix calculator division by zero",
  "description": "The calculator.py function divide crashes on zero input. Fix it.",
  "assets": [
    {"kind": "file", "location": "examples/code_fix/workspace/calculator.py", "label": "calculator.py"}
  ]
}
```

Example tasks are included under `examples/`: `code_fix`, `research_synth`, `writing_revision`, `experiment_loop`, and `self_review`.

## Configuration

Autodialectics resolves config in this order:

1. `--config PATH` flag
2. `AUTODIALECTICS_CONFIG` environment variable
3. `./autodialectics.yaml` in the current directory
4. `~/.config/autodialectics/autodialectics.yaml`

A typical local config:

```yaml
cliproxy_base_url: "http://127.0.0.1:8642"
cliproxy_api_key: ""
cliproxy_model: "default"
db_path: "autodialectics.db"
artifacts_dir: "artifacts"
benchmark_dir: "benchmarks/cases"
use_dspy_rlm: false
```

The model client speaks OpenAI-compatible `/v1/chat/completions`. Point `cliproxy_base_url` at any compatible endpoint -- Hermes Agent, LiteLLM, vLLM, Ollama, or the bundled CLI gateways.

### CLI gateways

Autodialectics ships three local gateways that expose CLI tools as OpenAI-compatible endpoints:

| Command | Backend | Notes |
|---------|---------|-------|
| `uv run claude-gateway` | Claude CLI | Wraps `claude` as `/v1/chat/completions` |
| `uv run codex-gateway` | Codex CLI | Wraps `codex exec` the same way |
| `uv run cli-gateway` | Auto-detect | Picks `claude`, `codex`, or `hermes` based on environment. Override with `CLI_GATEWAY_PROVIDER=codex\|claude\|hermes` |

Start a gateway, then point Autodialectics at it:

```bash
uv run cli-gateway &
uv run autodialectics run examples/code_fix/task.json
```

## REST API

```bash
uv run autodialectics serve --host 0.0.0.0 --port 8000 --reload
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/tasks/compile` | Compile a task into a contract |
| POST | `/runs` | Execute a full pipeline run |
| GET | `/runs/{run_id}` | Inspect a run |
| POST | `/benchmarks/run` | Run the benchmark suite |
| POST | `/policies/evolve` | Create a challenger policy |
| POST | `/policies/{policy_id}/promote` | Promote a challenger |
| POST | `/policies/rollback` | Rollback to previous champion |

## AI assistant integrations

Autodialectics includes first-class plugins for Claude Code, Codex, and OpenCode. All three share the same MCP server backend.

### Shared MCP server

```bash
uv run autodialectics-mcp
```

Exposes these tools over stdio: `health`, `init_runtime`, `compile_task`, `run_task`, `benchmark`, `inspect_run`, `read_artifact`, `evolve_policy`, `promote_policy`, `rollback_policy`, `replay_run`.

### Claude Code

The root `.mcp.json` auto-registers the MCP server when Claude Code opens this repo. Alternatively:

```bash
# Plugin directory mode
claude --plugin-dir ./claude-marketplace/plugins/autodialectics

# Local marketplace mode
/plugin marketplace add ./claude-marketplace
/plugin install autodialectics@autodialectics-marketplace
```

### Codex

The `.agents/plugins/marketplace.json` registers a repo-local Codex plugin with a skill at `plugins/autodialectics/skills/run/SKILL.md`.

### OpenCode

The `opencode.json` at the repo root configures the MCP server plus a local plugin at `.opencode/plugins/autodialectics.js`. Companion commands: `/autodialectics-run`, `/autodialectics-benchmark`. Review agent: `@autodialectics-review`.

### Validation

```bash
python scripts/validate_ai_integrations.py
uv run pytest tests/test_mcp_server.py -q
node --check .opencode/plugins/autodialectics.js
```

See [`docs/ai-plugin-integrations.md`](docs/ai-plugin-integrations.md) for full integration details.

## DSPy (optional)

Two optional paths use DSPy when available:

- **Recursive language-model exploration (RLM)** -- Deep evidence retrieval over long context, replacing the default heuristic chunker.
- **GEPA prompt evolution** -- Evolve challenger policies using DSPy optimization instead of heuristic mutation.

Both are capability-gated. If DSPy is unavailable or fails, the system falls back to heuristic behavior automatically. Enable with `use_dspy_rlm: true` in config and install with `uv sync --extra dspy`.

## Testing

```bash
# Full test suite
uv run pytest -q

# Live integration test (auto-skips if no local endpoint is reachable)
uv run pytest tests/test_integrations.py -m integration -q
```

CI runs the test suite on Python 3.11 and 3.12 with a packaging smoke check.

## Project layout

```
autodialectics/
  api/            # FastAPI routes
  cli/            # Typer CLI
  contract/       # Task contract compiler
  dialectic/      # Thesis/antithesis/synthesis planner
  evaluation/     # Slop scoring and run evaluation
  evolution/      # Champion/challenger policy management
  execution/      # Domain adapters (code, research, writing, etc.)
  exploration/    # Evidence gathering (heuristic + DSPy RLM)
  integrations/   # MCP server
  memory/         # Run memory and replay
  routing/        # Model client, CLI gateways
  schemas/        # Pydantic models
  storage/        # SQLite + artifact persistence
  utils/          # Shared utilities
benchmarks/       # Benchmark case definitions
configs/          # Example configuration files
docs/             # Reference architecture and integration docs
examples/         # Example task definitions
plugins/          # Codex plugin
claude-marketplace/  # Claude Code plugin
.opencode/        # OpenCode plugin
tests/            # Test suite
```

## License

MIT
