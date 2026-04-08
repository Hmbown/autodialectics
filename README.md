# Autodialectics

An agentic harness that keeps LLMs honest during research, code, and other high-drift work.

Instead of hoping a model stays on task, Autodialectics wraps every run in a structured pipeline: immutable contracts, evidence gathering, dialectical planning, domain-specific execution, independent verification, slop scoring, and champion/challenger policy evolution.

## Why

Most agent failures are control failures:

- The task changes shape mid-run
- Evidence is thin but confidence stays high
- Objections get ignored
- The system claims "done" without doing the hard part
- Evaluation collapses into self-congratulation

Autodialectics is the harness around that behavior.

## Current status

- Core pipeline is implemented and tested
- Code tasks support explicit repo/workspace roots, sandbox-copy execution, explicit verification commands, and bounded repair retries
- Hermes Agent API compatibility has been smoke-tested against a live local endpoint
- DSPy RLM and GEPA paths exist, but are capability-gated rather than assumed

## How it works

```text
Task JSON -> Contract Compiler -> Evidence Explorer -> Dialectical Planner
                                                         |
                                      Thesis -> Antithesis -> Synthesis
                                                         |
                                                Domain Execution
                                                         |
                                         Independent Verification
                                                         |
                                         Slop Scoring & Evaluation
                                                         |
                                                Gate Decision
                                              (accept / reject /
                                               revise / rollback)
                                                         |
                                         Champion/Challenger Evolution
```

1. Contract compilation locks the task into an immutable contract with objectives, deliverables, acceptance criteria, and forbidden shortcuts.
2. Evidence exploration loads attached assets and builds an evidence bundle using heuristic chunk scoring or DSPy-assisted retrieval.
3. Dialectical planning forces the system through thesis, antithesis, and synthesis. The first plan never stands uncontested.
4. Execution uses domain adapters for code, research, writing, experiment, analysis, or generic tasks.
5. Verification evaluates output against the contract from a fresh perspective.
6. Evaluation scores slop dimensions like unsupported claims, fake completion, requirement drift, benchmark gaming, and redundancy.
7. Gate accepts, rejects, revises, or rolls back based on evidence.
8. Evolution creates challenger policies from benchmark evidence and promotes only when they outperform the champion without increasing slop.

## Install

```bash
git clone https://github.com/Hmbown/autodialectics.git
cd autodialectics
pip install uv
uv sync
```

Optional extras:

```bash
uv sync --extra dev
uv sync --extra dspy
```

## Quick start

```bash
# Initialize local state
uv run autodialectics init

# Compile a task into an immutable contract
uv run autodialectics compile examples/code_fix/task.json

# Run the full pipeline
uv run autodialectics run examples/code_fix/task.json

# Inspect a completed run
uv run autodialectics inspect <run_id>

# Replay a prior run from the stored submission artifact
uv run autodialectics replay <run_id>

# Run benchmarks and evolve policy
uv run autodialectics benchmark
uv run autodialectics evolve
```

## Task format

Tasks are JSON files with a title, description, and optional attached assets:

```json
{
  "title": "Fix calculator division by zero",
  "description": "The calculator.py function divide crashes on zero input. Fix it.",
  "domain": "code",
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

Examples are included under `examples/`: `code_fix`, `research_synth`, `writing_revision`, `experiment_loop`, and `self_review`.

## Autonomous repo-work tasks

For code tasks that should actually edit and verify a real repository, prefer an explicit workspace root plus explicit verification commands:

- `workspace_root` controls what gets copied into the sandbox for execution and verification
- `assets` remain the evidence set for planning and grounding, so you do not need to dump the whole repo into the prompt path
- `verification_commands` override heuristic test discovery and are the preferred mode for real repository work
- `max_repair_attempts` enables a bounded fix-verify-repair loop instead of a single-shot code response

The code adapter copies the workspace into an isolated sandbox, includes a compact workspace snapshot in the executor prompt, runs verification commands, and retries with failure feedback up to the configured repair budget.

## Configuration

Autodialectics resolves config in this order:

1. `--config PATH`
2. `AUTODIALECTICS_CONFIG`
3. `./autodialectics.yaml`
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

The model client speaks OpenAI-compatible `/v1/chat/completions`. Point `cliproxy_base_url` at any compatible endpoint.

## CLI gateways

Autodialectics ships local gateways that expose CLI tools as OpenAI-compatible endpoints:

- `uv run claude-gateway`
- `uv run codex-gateway`
- `uv run cli-gateway`

`cli-gateway` auto-detects the active local CLI environment and can be overridden with `CLI_GATEWAY_PROVIDER=codex|claude|hermes`.

## REST API

```bash
uv run autodialectics serve --host 0.0.0.0 --port 8000 --reload
```

Core endpoints:

- `GET /health`
- `POST /tasks/compile`
- `POST /runs`
- `GET /runs/{run_id}`
- `POST /benchmarks/run`
- `POST /policies/evolve`
- `POST /policies/{policy_id}/promote`
- `POST /policies/rollback`

## AI assistant integrations

All AI assistant surfaces share the same MCP backend: `uv run autodialectics-mcp`.

- Claude Code: root `.mcp.json` plus the local marketplace under `claude-marketplace/`
- Codex: repo-local marketplace at `.agents/plugins/marketplace.json` with plugin files under `plugins/autodialectics/`
- OpenCode: `opencode.json` plus local files under `.opencode/`

Validation and integration details live in [docs/ai-plugin-integrations.md](docs/ai-plugin-integrations.md).

## DSPy

Two optional paths use DSPy when available:

- Recursive language-model exploration for long-context evidence retrieval
- GEPA prompt evolution for challenger policy optimization

If DSPy is unavailable or fails, the system falls back to heuristic behavior automatically.

## Testing

```bash
# Full suite
uv run pytest -q

# Optional live integration smoke tests
uv run pytest tests/test_integrations.py -m integration -q
```

The integration tests auto-skip if a local endpoint is not reachable.

## Project layout

```text
autodialectics/
├── autodialectics/
│   ├── api/
│   ├── cli/
│   ├── contract/
│   ├── dialectic/
│   ├── evaluation/
│   ├── evolution/
│   ├── execution/
│   ├── exploration/
│   ├── integrations/
│   ├── memory/
│   ├── routing/
│   ├── schemas/
│   ├── storage/
│   └── utils/
├── benchmarks/
├── claude-marketplace/
├── configs/
├── docs/
├── examples/
├── plugins/
└── tests/
```

## Near-term priorities

- Strengthen integration tests around live OpenAI-compatible endpoints
- Harden DSPy/GEPA benchmarking semantics
- Extend code sandboxing if stricter isolation becomes necessary

## License

MIT
