# Autodialectics

Autodialectics is an agentic harness for keeping an LLM on-task during research and other high-drift work.

Instead of asking a model to “just do the task” and hoping it stays honest, it wraps the run in structure:
- immutable task contracts
- evidence gathering
- thesis → antithesis → synthesis planning
- domain-specific execution
- independent verification
- slop scoring
- gate decisions
- champion/challenger policy evolution

The goal is simple: reduce drift, fake completion, unsupported claims, and benchmark-gaming while still letting the underlying model do useful work.

Autodialectics is especially shaped for Hermes Agent environments. The default local model route assumes the Hermes Agent API server at http://127.0.0.1:8642, but any OpenAI-compatible chat-completions endpoint can be used.

Current status
- Core pipeline is implemented and tested.
- Code tasks now support explicit repo/workspace roots, sandbox-copy execution, explicit verification commands, and bounded repair retries.
- Hermes Agent API compatibility has been smoke-tested against a live local Hermes endpoint.
- DSPy RLM and GEPA paths exist, but remain optional and should be treated as capability-gated rather than universally available.

Core pipeline
1. Contract compilation
   Normalize a task into an immutable contract with objectives, deliverables, acceptance criteria, and forbidden shortcuts.
2. Evidence exploration
   Load attached assets and build an evidence bundle with either heuristic chunk scoring or DSPy-assisted retrieval.
3. Dialectical planning
   Force the system through thesis, antithesis, and synthesis instead of letting the first plan stand uncontested.
4. Execution
   Domain adapters execute code, research, writing, experiment, analysis, or generic tasks.
5. Verification
   Evaluate the output against the contract from a fresh perspective.
6. Evaluation
   Score slop: unsupported claims, fake completion, requirement drift, benchmark gaming, and other failure modes.
7. Gate
   Accept, reject, revise, rollback, or promote.
8. Evolution
   Create challenger policies from benchmark evidence and promote only when they outperform the champion without increasing slop.

Why this exists
Most agent failures are not pure intelligence failures. They are control failures:
- the task changes shape halfway through
- evidence is thin but confidence stays high
- objections are ignored
- the system claims completion without doing the hard part
- evaluation collapses into self-congratulation

Autodialectics is meant to be the harness around that behavior.

Hermes Agent integration
Default local route:
- Hermes API server: http://127.0.0.1:8642

Typical local config:
```yaml
cliproxy_base_url: "http://127.0.0.1:8642"
cliproxy_api_key: ""
cliproxy_model: "default"
db_path: "autodialectics.db"
artifacts_dir: "artifacts"
benchmark_dir: "benchmarks/cases"
use_dspy_rlm: false
dspy_api_base: null
dspy_api_key: null
rlm_threshold_chars: 8000
max_evidence_items: 20
```

Hermes compatibility notes
- The model client speaks OpenAI-compatible /v1/chat/completions.
- If the endpoint is unavailable, Autodialectics falls back to heuristic/offline behavior instead of pretending the model call succeeded.
- A local live smoke test against the Hermes API path is included as an optional integration test.

Alternative local gateways
- `claude-gateway` exposes the Claude CLI as an OpenAI-compatible `/v1/chat/completions` server.
- `codex-gateway` exposes `codex exec` the same way, which is useful when you want Autodialectics to use the Codex CLI as the backend model route.
- `cli-gateway` auto-detects the active local CLI environment and routes to `codex`, `claude`, or `hermes`. Set `CLI_GATEWAY_PROVIDER=codex|claude|hermes|auto` to override detection.

Example Codex gateway flow
```bash
uv run codex-gateway
```

Example auto-detecting gateway flow
```bash
uv run cli-gateway
```

Then point Autodialectics at it:
```yaml
cliproxy_base_url: "http://127.0.0.1:8642"
cliproxy_model: "gpt-5.4-mini"
```

What is real vs optional
Implemented and exercised
- contract compiler
- runtime orchestration
- dialectic engine
- benchmark runner
- FastAPI surface
- Typer CLI
- SQLite/file artifact persistence
- code-task sandbox verification with replayable submissions
- heuristic challenger creation

Implemented but capability-gated
- DSPy recursive language-model exploration path
- DSPy GEPA optimization path

Important caveat on DSPy paths
- These paths are real code paths, not marketing copy.
- They are also optional and environment-dependent.
- If DSPy is unavailable or fails, the system falls back to heuristic exploration or heuristic challenger mutation.
- DSPy RLM here means recursive language-model exploration over long context, not a plain retrieval-only pass.
- Current automated tests verify fallback and capability-gating behavior for DSPy paths; they do not yet prove a fully configured positive-path DSPy runtime in CI.
- `dspy_api_base` and `dspy_api_key` can override the DSPy endpoint, but the default positive path now routes DSPy through the configured OpenAI-compatible `cliproxy` endpoint.
- The current GEPA implementation is intentionally conservative and should be described as experimental rather than production-hardened optimization.

Reference architecture
- See `docs/reference_flow.md` for the mermaid reference flow covering routing, recursive evidence exploration, dialectics, execution, verification, storage, benchmarking, and champion/challenger evolution.

Installation
```bash
git clone https://github.com/Hmbown/autodialectics.git
cd autodialectics
pip install uv
uv sync
```

Optional extras
```bash
uv sync --extra dev
uv sync --extra dspy
```

Quick start
Initialize local state:
```bash
autodialectics init
```

Compile a task:
```bash
autodialectics compile examples/code_fix/task.json
```

Run a task:
```bash
autodialectics run examples/code_fix/task.json
```

Autonomous repo-work tasks
- Code tasks can now declare `workspace_root`, `verification_commands`, and `max_repair_attempts` in the task JSON.
- The code adapter copies the workspace into an isolated sandbox, includes a compact workspace snapshot in the executor prompt, runs verification commands, and retries with failure feedback up to the configured repair budget.
- `examples/code_fix/task.json` is the reference fixture for this workflow.

Example task shape:
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

Replay a prior run from the stored submission artifact:
```bash
autodialectics replay <run_id>
```

Run the benchmark suite:
```bash
autodialectics benchmark
```

Serve the API:
```bash
autodialectics serve --host 0.0.0.0 --port 8000 --reload
```

Autonomous repo-work task shape
For code tasks that should actually edit and verify a real repository, prefer an explicit workspace root plus explicit verification commands:

```json
{
  "title": "Fix failing regression in the parser",
  "description": "Implement the fix and prove it with the parser tests.",
  "domain": "code",
  "workspace_root": ".",
  "verification_commands": [
    "python -m pytest -q tests/test_parser.py"
  ],
  "max_repair_attempts": 3,
  "assets": [
    {
      "kind": "file",
      "location": "parser.py",
      "label": "parser.py"
    },
    {
      "kind": "file",
      "location": "tests/test_parser.py",
      "label": "tests/test_parser.py"
    }
  ]
}
```

Notes:
- `workspace_root` controls what gets copied into the sandbox for execution and verification.
- `assets` remain the evidence set for planning and grounding, so you do not need to dump the whole repo into the prompt path.
- `verification_commands` override heuristic test discovery and are the preferred mode for real repository work.
- `max_repair_attempts` enables a bounded fix-verify-repair loop instead of a single-shot code response.

Configuration resolution order
1. --config PATH
2. AUTODIALECTICS_CONFIG
3. ./autodialectics.yaml
4. ~/.config/autodialectics/autodialectics.yaml

To create a local config:
```bash
cp configs/autodialectics.example.yaml autodialectics.yaml
```

API endpoints
- GET /health
- POST /tasks/compile
- POST /runs
- GET /runs/{run_id}
- POST /benchmarks/run
- POST /policies/evolve
- POST /policies/{policy_id}/promote
- POST /policies/rollback

AI assistant integrations
- Codex: repo-local marketplace at `.agents/plugins/marketplace.json` and plugin files under `plugins/autodialectics/`
- Claude Code: local marketplace at `claude-marketplace/.claude-plugin/marketplace.json`
- OpenCode: project config at `opencode.json` plus local files under `.opencode/`
- Shared backend: all three surfaces use the same MCP entrypoint, `uv run autodialectics-mcp`
- Validation guide: `docs/ai-plugin-integrations.md`
- Verification prompt for another agent: `test.md`

Testing
Run the full suite:
```bash
python -m pytest -q
```

Run the optional live Hermes API smoke test:
```bash
python -m pytest tests/test_integrations.py -m integration -q
```

The integration test auto-skips if a local Hermes API server is not reachable.

CI
GitHub Actions runs:
- test suite on Python 3.11 and 3.12
- packaging smoke check via python -m compileall

Project layout
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
│   ├── memory/
│   ├── routing/
│   ├── schemas/
│   ├── storage/
│   └── utils/
├── benchmarks/
├── configs/
├── docs/
├── examples/
└── tests/
```

Near-term priorities
- strengthen integration tests around live OpenAI-compatible endpoints
- harden DSPy/GEPA benchmarking semantics
- extend code sandboxing if stricter isolation becomes necessary

License
MIT
