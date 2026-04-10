# Design Anchor

This file is the design anchor for Autodialectics. It is intended to be symlinked into agent-facing instruction files so that future edits, integrations, and feature work stay aligned with the same architectural spine.

It is not a full architecture dump. It is the set of decisions that should remain true unless we explicitly decide to change the project itself.

## Product Thesis

Autodialectics is not "an agent."

It is a harness around model behavior. Its job is to reduce high-confidence drift by forcing work through explicit stages: contract, evidence, dialectic, execution, verification, evaluation, and gate decision.

The project succeeds when it makes weak or sloppy model behavior legible, containable, and rejectable. It does not succeed merely by producing output.

## What We Are Building

Autodialectics is a Python-first runtime with three responsibilities:

1. Turn loose task submissions into immutable, inspectable contracts.
2. Route execution through a structured pipeline that preserves evidence, objections, verification, and scoring.
3. Persist enough state and artifacts that a run can be inspected, benchmarked, compared, replayed, and evolved.

Everything else is a surface around that runtime.

## Core Design Commitments

### 1. The runtime is the system of record

The canonical behavior lives in the Python package under [`autodialectics/`](/Volumes/VIXinSSD/autodialectics/autodialectics). CLI commands, REST endpoints, MCP tools, Codex/Claude/OpenCode plugins, and local gateways are all adapters over the same runtime.

Design rule:
- Do not let an integration surface reimplement core pipeline logic.
- If behavior must change, change the runtime first, then let the surfaces inherit it.

### 2. The pipeline is the product

The main value is not any individual stage. It is the sequence.

The intended spine is:

`TaskSubmission -> TaskContract -> EvidenceBundle -> DialecticArtifact -> ExecutionArtifact -> VerificationReport -> RunEvaluation -> Gate decision -> persisted artifacts / benchmark signals / policy evolution`

Design rule:
- New features should attach to this spine, not bypass it.
- If a stage is skipped, that must be explicit and inspectable, never implicit.

### 3. Contracts are anti-drift devices

The contract exists to freeze the job before the model starts improvising. It captures objectives, constraints, deliverables, acceptance criteria, forbidden shortcuts, workspace scope, verification commands, repair budget, and a source hash.

Design rule:
- Treat the contract as immutable once compiled.
- Do not silently rewrite objectives downstream to make a run easier to pass.

### 4. Evidence must be explicit

Evidence is not a vibe. The system loads assets, chunks them, scores them, records gaps, and passes a concrete bundle forward.

The explorer may be heuristic or DSPy-assisted, but both paths must yield the same kind of artifact: an inspectable `EvidenceBundle`.

Design rule:
- Claims about grounding should always point back to recorded evidence or to a declared gap.
- Retrieval sophistication can change; evidence explicitness cannot.

### 5. Opposition is mandatory, not decorative

The thesis-antithesis-synthesis sequence is not branding. It is the mechanism that forces the first plan to face criticism before execution.

Design rule:
- Do not collapse dialectics into a single hidden prompt.
- Preserve objection records and dispositions because downstream evaluation depends on them.

### 6. Verification must stay independent from execution

The executor cannot be allowed to certify itself. Verification should read the original contract and the produced artifact from a fresh perspective.

Current verification is heuristic and intentionally lightweight, but the architectural boundary is correct and should be preserved even if the implementation becomes stronger.

Design rule:
- Never merge execution and verification into one opaque "model says it worked" step.

### 7. Slop is first-class

Autodialectics is explicitly opinionated about failure modes such as fake completion, unsupported claims, requirement drift, synthesis ignoring objections, and benchmark gaming.

Design rule:
- Slop scoring is not a cosmetic post-processing layer.
- New evaluation work should make slop detection sharper, not easier to game.

### 8. Promotion must be conservative

Champion/challenger evolution exists to improve policy surfaces without letting the system self-congratulate into regression.

Design rule:
- Promotion should require comparative benchmark evidence and canary protection.
- "The new prompt feels better" is not a promotion criterion.

## Architectural Boundaries

### Runtime boundary

The runtime in [`autodialectics/runtime/runner.py`](/Volumes/VIXinSSD/autodialectics/autodialectics/runtime/runner.py) owns orchestration. It wires together compilation, exploration, planning, execution, verification, evaluation, storage, and evolution.

This file should remain the place where the full run is understandable end to end.

### Domain boundary

Domain adapters are allowed to differ in prompt construction and execution semantics, but they should all return the same `ExecutionArtifact` shape.

Code execution is the sharpest version of this boundary:
- it materializes an isolated workspace copy
- applies full-file replacements from the model
- runs explicit or inferred verification commands
- supports bounded repair retries
- records sandbox details in structured output

Design rule:
- Code tasks should continue to prefer sandboxed verification over direct mutation of the source repo.
- Domain adapters may specialize behavior, but they should not invent incompatible artifact contracts.

### Storage boundary

Autodialectics stores both durable files and indexable records:
- artifact files on disk for legibility
- SQLite rows for lookup, comparison, replay, and policy state

This dual persistence model is correct. Files are for humans and audits; SQLite is for orchestration and tooling.

Design rule:
- Do not move to database-only persistence.
- Do not treat artifacts as optional logs.

### Integration boundary

MCP, CLI, REST, Claude/Codex/OpenCode plugin surfaces, and local model gateways are all thin integration layers. Their job is translation and exposure, not policy.

Design rule:
- Integrations should be cheap to maintain and easy to replace.
- If an integration starts accumulating core logic, it is probably in the wrong place.

## Model Routing Philosophy

The model client speaks OpenAI-compatible chat completions. That is the right abstraction for the current system because it keeps the runtime portable across local gateways and external endpoints.

The routing layer should remain replaceable. Today that means:
- direct OpenAI-compatible endpoints via `ModelClient`
- local CLI-backed gateways for Codex, Claude, and auto-selected local CLIs
- optional DSPy use for recursive exploration and GEPA

Design rule:
- Keep routing generic and runtime-facing.
- Avoid coupling core logic to a specific vendor CLI or provider-specific response shape.

## Failure Semantics

Autodialectics should distinguish between:

- `offline`: no LLM backend is configured, so heuristic-only behavior is expected
- `request failure`: an LLM backend was configured but failed to produce a usable response
- `task failure`: the system ran and the task did not satisfy the contract

Those are different states and should stay different.

Design rule:
- Preserve explicit failure signaling.
- Do not let transport failure masquerade as task success.

## Current Deployment Shape

The current shape is intentionally Python-first:
- Typer CLI for local use
- FastAPI for HTTP access
- FastMCP server for assistant integrations
- SQLite plus artifact files for persistence
- autonomous loops such as autopilot built by composing benchmark, evolution, and promotion primitives rather than introducing a second execution model

There is a documented aspiration toward a Go sidecar for routing and registry concerns, but that is secondary. The Python runtime is the product today.

Design rule:
- Optimize the current Python-first lane until the routing sidecar becomes clearly necessary.
- Do not prematurely split the system into services.

## Non-Goals

Autodialectics should not drift into any of these:

- a general-purpose autonomous agent framework with vague internal state
- an opaque orchestration layer that hides intermediate reasoning artifacts
- a benchmark optimizer that quietly sacrifices rigor for score
- an integration-led project where each client surface behaves differently
- a retrieval-heavy system that confuses more context with better evidence

## Extension Rules

When adding new work, prefer these moves:

1. Add or sharpen artifact structure before adding prompt cleverness.
2. Strengthen verification before strengthening self-description.
3. Add explicit configuration for execution-critical behavior rather than heuristics hidden in prompts.
4. Keep new external surfaces thin and runtime-backed.
5. Treat tests as part of the design contract, not a trailing concern.

When choosing between two designs, prefer the one that makes these things easier:

- inspection after the fact
- replay
- benchmark comparison
- conservative failure
- grounded verification

## What Should Feel Stable

These should remain stable unless we consciously decide to redefine the project:

- the runtime is the source of truth
- contracts are immutable
- evidence is explicit
- dialectics are preserved
- verification is independent
- slop is a first-class evaluation target
- promotion is benchmark-gated
- integrations are thin

## What Can Change Freely

These are implementation choices, not identity:

- exact prompt wording
- heuristic thresholds
- scoring formulas and metric weights
- gateway implementation details
- artifact formatting details
- the choice to use DSPy or a different optimization/retrieval helper
- the eventual introduction of a routing sidecar

## Practical Guidance For Agents And Contributors

If you are changing this repo:

- start from the pipeline, not from the surface you happen to be touching
- ask whether the change improves legibility, grounding, verification, or benchmark integrity
- avoid convenience abstractions that hide important intermediate state
- prefer explicit artifacts over implicit magic
- if a shortcut makes the system look better while making failure harder to see, reject it

If a proposed change conflicts with this document, either:

1. change the proposal, or
2. change this document first, explicitly, because the project itself is changing

That is the standard for design drift.
