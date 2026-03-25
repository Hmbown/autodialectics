# Architecture

Autodialectics is an anti-slop agentic operating system that wraps any LLM in a structured pipeline designed to minimize AI-generated slop (verbose, ungrounded, or superficially plausible output) while maximizing genuine task success.

## Pipeline Stages

The core pipeline processes every task through these sequential stages:

### 1. Contract Compilation
A `TaskSubmission` (title + description + optional constraints/objectives) is compiled into an immutable `TaskContract`. The compiler infers the task domain (CODE, RESEARCH, WRITING, EXPERIMENT, ANALYSIS, GENERIC) from keywords, normalizes deliverables and acceptance criteria from domain-specific defaults, and produces a SHA-256 source hash for immutability verification.

### 2. Evidence Exploration
Assets attached to the task (files, inline text, directories) are loaded and chunked. The `ContextExplorer` builds an `EvidenceBundle` by scoring chunks against exploration queries using keyword-overlap heuristics, or via DSPy RLM for longer contexts (>8000 chars).

### 3. Dialectical Planning
The `DialecticalPlanner` generates a three-phase dialectic:
- **Thesis**: A step-by-step execution plan based on the contract and evidence.
- **Antithesis**: Critical objections to the thesis, rated by severity (0.0-1.0).
- **Synthesis**: A revised plan that explicitly addresses all serious objections.

This dialectic structure forces the system to confront its own weaknesses before executing.

### 4. Execution
A domain-specific `ExecutionAdapter` (code, research, writing, experiment, analysis, or generic) constructs prompts from the contract, evidence, and dialectic, then calls the LLM to produce an `ExecutionArtifact` with output text, patches, test results, and declared uncertainties.

### 5. Verification
An independent `RunEvaluator.verify()` step checks the execution output against the contract's acceptance criteria using keyword overlap analysis. It produces a `VerificationReport` with per-criterion checks, a pass/fail verdict, and independent findings (e.g., suspicious absence of declared uncertainties).

### 6. Evaluation
The `RunEvaluator.evaluate_run()` produces a composite `RunEvaluation` with weighted scores for task success, groundedness, objection coverage, novelty usefulness, requirement fidelity, and verification quality. A `SlopScore` comprising 12 sub-metrics detects patterns like fake completion, unsupported claims, verbosity without gain, and benchmark gaming.

### 7. Gate Decision
The `AdvanceGate` makes one of four decisions:
- **Accept**: Verification passed, score >= 0.6, slop < 0.4
- **Reject**: Verification failed badly or excessive slop
- **Revise**: Middle ground, improvement needed

### 8. Artifact Persistence
All intermediate artifacts (contract, evidence, dialectic, execution, verification, evaluation, summary) are persisted as JSON/Markdown files in the artifacts directory and tracked in SQLite.

### 9. Evolution
The `ChampionChallengerManager` supports policy evolution:
- **Evolve**: Create a challenger policy from benchmark reports (using DSPy GEPA or heuristic mutation)
- **Compare**: Evaluate challenger vs champion on score improvement and slop reduction
- **Promote**: Promote challenger to champion if it outperforms on all metrics
- **Rollback**: Revert to the previous champion

## Deployment Lanes

### Lane 1: Python-First MVP (Current)
The entire system runs as a Python package:
- FastAPI server for HTTP API
- Typer CLI for direct command-line usage
- SQLite for persistence
- httpx for LLM calls to any OpenAI-compatible endpoint

### Lane 2: Go Sidecar (Planned)
A Go-based CLIProxyAPI sidecar handles:
- Model routing and load balancing
- API key management
- Model registry and hot-reload
- Request/response hooks for monitoring

The Python runtime communicates with the sidecar via its OpenAI-compatible `/v1/chat/completions` endpoint.

## Key Anti-Slop Mechanisms

1. **Immutable Contracts**: Once compiled, a task contract cannot be silently rewritten during execution. The source hash prevents post-hoc modification of objectives.

2. **Evidence Bundles**: All claims must be grounded in loaded evidence. The evidence bundle tracks which sources were consulted and what gaps remain.

3. **Dialectical Opposition**: The mandatory antithesis stage forces the system to identify its own weaknesses before producing output, reducing over-confidence and blind spots.

4. **Execution/Verification Split**: The verification step uses a fresh, independent analysis of the execution output against the original criteria, preventing the executor from self-certifying its work.

5. **SlopScore (12 metrics)**: A composite of 12 slop sub-metrics detects fake completion, unsupported claims, verbosity without gain, repetition, requirement drift, self-verification bias, benchmark gaming, shallow novelty, context contamination, refusal to surface uncertainty, tool abuse, and synthesis ignoring objections.

6. **Champion/Challenger Evolution**: Policies are evolved through systematic comparison on benchmark suites including canary cases designed to detect benchmark gaming. A new policy must demonstrably outperform the champion on both score and slop before promotion.
