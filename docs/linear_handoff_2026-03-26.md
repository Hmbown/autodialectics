# Linear Handoff: Reliability And Verification Follow-Ups

Context:
- The current `cli-gateway` path now works end to end with the active local CLI as the backend model route.
- Live verification passed for code, writing, research, and a fresh 5-case benchmark run through the Codex-backed proxy.
- The main remaining risk surface is not transport; it is evaluation and benchmark robustness.
- Linear MCP was not authenticated in this session, so these are issue-ready drafts rather than already-created tickets.

Suggested project:
- `autodialectics`

Suggested labels:
- `Bug`
- `Improvement`
- `Infra`
- `Evaluation`

## 1. Replace benchmark phrase matching with structured expectation scoring

Priority: High  
Suggested label: Improvement

Title:
`Replace benchmark keyword checks with structured expectation scoring`

Description:
The current benchmark scorer in [`autodialectics/runtime/runner.py`](/Volumes/VIXinSSD/autodialectics/autodialectics/runtime/runner.py) still relies on `must_include` and `must_not_include` substring checks. That path was recently patched to inspect execution artifacts and ignore quoted forbidden phrases, but it is still brittle.

Why this matters:
- Canary cases can fail or pass for wording reasons rather than behavior reasons.
- Quoted benchmark instructions can look like forbidden output.
- Required concepts are currently validated with literal phrase presence instead of structured evidence.

Scope:
- Extend `BenchmarkCase.expectation` to support structured expectations, not just flat phrase lists.
- Allow checks like:
  - required sections
  - required evidence/reference markers
  - forbidden certainty assertions as asserted claims rather than quoted warnings
  - expected verification/evaluation thresholds
- Keep backward compatibility for existing benchmark JSON files.
- Update benchmark reports to record which structured checks passed or failed.

Acceptance criteria:
- Benchmark scoring no longer depends only on `record.summary`.
- Quoted “do not say X” language does not trigger the forbidden-phrase penalty.
- Existing benchmark cases still load and run.
- New tests cover positive, negative, and quoted-language edge cases.

## 2. Replace overlap-heavy verification fallbacks with schema-driven domain checks

Priority: High  
Suggested label: Improvement

Title:
`Make verification domain-specific and schema-driven instead of overlap-heavy`

Description:
Verification in [`autodialectics/evaluation/slop.py`](/Volumes/VIXinSSD/autodialectics/autodialectics/evaluation/slop.py) has improved, but several domains still fall back to keyword overlap when a more concrete structural check is possible. Analysis and experiment handling were recently patched, but the overall approach remains heuristic-first.

Why this matters:
- Good outputs can still score as partial or fail when wording shifts.
- Domain checks should inspect structure, evidence anchoring, and explicit support markers.
- The current fallback makes benchmark outcomes noisier than they need to be.

Scope:
- Define explicit domain verifiers for:
  - analysis
  - experiment
  - research
  - writing
  - code no-op / verification-backed cases
- Prefer structural checks before keyword overlap.
- Reserve overlap-based fallback only for genuinely generic criteria.
- Consider introducing a normalized verifier helper layer so domain checks do not keep growing ad hoc inside one file.

Acceptance criteria:
- Analysis tasks with explicit alternative-interpretation and evidence-linked conclusions pass without relying on overlap.
- Experiment protocols are validated using reproducibility/statistics structure, not loose term overlap.
- Research and writing verifiers remain green on existing tests.
- New tests cover false-positive and false-negative regressions from recent live runs.

## 3. Make benchmark case domains explicit instead of relying on inference

Priority: Medium  
Suggested label: Bug

Title:
`Add explicit domain to benchmark fixtures and reduce inference sensitivity`

Description:
The long-context canary case was misclassified during live runs because contract compilation inferred the wrong domain from incidental keywords like `benchmark` or `test`. The compiler has been patched in [`autodialectics/contract/compiler.py`](/Volumes/VIXinSSD/autodialectics/autodialectics/contract/compiler.py), but benchmark fixtures should not rely on inference for correctness.

Why this matters:
- Benchmark reliability should not depend on incidental wording in titles/descriptions.
- Domain inference is appropriate for user submissions, but benchmark fixtures are controlled inputs and can be explicit.

Scope:
- Add `domain` explicitly to benchmark case submissions where appropriate.
- Update benchmark fixtures under [`benchmarks/cases`](/Volumes/VIXinSSD/autodialectics/benchmarks/cases) to stop depending on compiler guesswork.
- Keep compiler inference improvements for general submissions, but reduce benchmark sensitivity to inference changes.
- Add regression tests showing that benchmark outcomes do not shift just because a fixture title changes slightly.

Acceptance criteria:
- All benchmark cases declare an explicit domain unless there is a deliberate test for inference.
- Benchmark outcomes remain stable if non-semantic wording changes in the fixture metadata.
- Compiler tests still cover general-purpose domain inference for normal submissions.

## 4. Add a provider-matrix live integration harness for `cli-gateway`

Priority: Medium  
Suggested label: Infra

Title:
`Add capability-gated live integration coverage for cli-gateway providers`

Description:
The local gateway path now works with Codex in live runs, including `model=default` resolution and runtime flag handling. Similar coverage should exist for the provider matrix, especially since the product goal is “use the active local CLI as the backend model route.”

Why this matters:
- The live path is stronger than it was, but only Codex was fully validated in this session.
- `auto`, explicit provider override, runtime flags, and provider-specific model defaults should be exercised consistently.

Scope:
- Add capability-gated integration tests for:
  - `cli-gateway --provider auto`
  - `cli-gateway --provider codex`
  - `cli-gateway --provider claude`
  - `cli-gateway --provider hermes`
- Validate:
  - health endpoint reports expected provider
  - model default resolution works
  - `ModelClient` round-trips a sentinel string
  - one representative end-to-end task runs when the provider is available
- Keep tests auto-skipping if the corresponding CLI is unavailable.

Acceptance criteria:
- Live provider tests are present and documented as optional integration coverage.
- Failures clearly separate auth/availability problems from product regressions.
- `cli-gateway`, `codex-gateway`, and `claude-gateway` runtime flag behavior stays covered.

## 5. Reduce false positives in benchmark-gaming and fake-completion detection

Priority: Medium  
Suggested label: Improvement

Title:
`Reduce false positives in overconfidence and fake-completion detection`

Description:
Internal evaluation still has some brittle heuristics around benchmark-gaming and completion claims. One recent example: quoted warning text about certainty was treated as risky output. Another recurring risk is treating plan-like or provenance-heavy responses as fake completion when they are actually correctly constrained.

Why this matters:
- Reliability scoring should catch risky behavior without punishing grounded caution.
- False positives distort both benchmark outcomes and policy evolution.

Scope:
- Audit:
  - `_benchmark_gaming`
  - `_fake_completion`
  - related confidence/uncertainty heuristics in [`autodialectics/evaluation/slop.py`](/Volumes/VIXinSSD/autodialectics/autodialectics/evaluation/slop.py)
- Distinguish:
  - quoted or cited risky language
  - warnings about risky language
  - actual overconfident assertions
- Add provenance-aware exceptions where the system is explicitly describing the benchmark or quoting source material.

Acceptance criteria:
- Quoted benchmark instructions do not inflate the benchmark-gaming metric.
- Provenance-heavy analysis outputs do not get misread as fake completion without evidence.
- New tests cover quoted-language, canary, and cautious-refusal cases.

## 6. Add a stable handoff benchmark for “anti-overconfidence” behavior

Priority: Medium  
Suggested label: Evaluation

Title:
`Add benchmark fixtures for ambiguity handling, uncertainty, and provenance discipline`

Description:
The current canary fixture is useful, but it is doing multiple jobs at once: ambiguity, contradiction, anti-overclaiming, and benchmark-gaming detection. It would be better to break this into a small benchmark family so behavior can be diagnosed more precisely.

Why this matters:
- One canary currently compresses several failure modes into one score.
- It is hard to tell whether a regression came from contradiction handling, uncertainty labeling, provenance loss, or literal phrase scoring.

Scope:
- Add additional benchmark fixtures for:
  - explicit contradiction preservation
  - unsupported-answer refusal
  - provenance-heavy synthesis
  - quoted-instruction handling
  - ambiguity without contradiction
- Keep the current canary, but complement it with narrower fixtures.
- Update docs so future agents know what each fixture is testing.

Acceptance criteria:
- Benchmark suite includes multiple ambiguity/uncertainty fixtures with distinct purposes.
- Each fixture has a documented failure mode and expectation.
- At least one live benchmark run verifies the expanded fixture set through `cli-gateway`.
