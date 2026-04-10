---
name: inspect
description: Examine Autodialectics run results, manifests, and stored artifacts. Use after a pipeline run completes or to review past runs.
---

# Autodialectics Inspect

Use this skill to examine completed or in-progress pipeline runs and their artifacts.

## Prerequisites

`autodialectics-mcp` must be on PATH (`pip install autodialectics`).

## MCP Tools

- **`inspect_run(run_id)`** — retrieve the run manifest: status, decision, scores, timing, and artifact paths.
- **`read_artifact(run_id, artifact_name)`** — read a specific artifact by filename. Artifacts by pipeline stage:
  1. `submission.json` — the original task submission
  2. `contract.md` — the immutable task contract (Markdown)
  3. `evidence.json` — gathered evidence bundle from the exploration stage
  4. `dialectic.json` — thesis/antithesis/synthesis from the dialectical planner
  5. `execution.json` — domain executor results
  6. `verification.json` — independent verification output
  7. `evaluation.json` — slop scores and gate decision
  8. `summary.md` — human-readable run summary
  9. `benchmark_report.json` — benchmark-specific metrics (only present for benchmark runs)

## CLI Fallback

```bash
autodialectics inspect <run_id>
```

## Guidance

- Start with `inspect_run` to get the overview, then drill into specific artifacts with `read_artifact`.
- When summarizing a run, always include: run ID, domain, policy ID, decision, overall score, slop composite.
- If the run status is `running` or `starting`, it may still be in progress — wait and re-inspect.
- Compare `verification.json` against `evaluation.json` to understand whether the verifier and evaluator agree.
- Read `dialectic.json` to see how the planner resolved competing concerns (thesis vs antithesis).

## Arguments

If the user passes a run ID after `/autodialectics:inspect`, inspect that run and summarize the results.
