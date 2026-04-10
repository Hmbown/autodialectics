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
- **`read_artifact(run_id, artifact_name)`** — read a specific artifact by filename. Common artifacts:
  - `contract.json` — the immutable task contract
  - `submission.json` — the original task submission
  - `execution_output.json` — domain executor results
  - `verification_result.json` — independent verification output
  - `evaluation.json` — slop scores and gate decision
  - `pre_mortem.json` — failure predictions (if pre-mortem routing was enabled)

## CLI Fallback

```bash
autodialectics inspect <run_id>
```

## Guidance

- Start with `inspect_run` to get the overview, then drill into specific artifacts with `read_artifact`.
- When summarizing a run, always include: run ID, domain, policy ID, decision, overall score, slop composite.
- If the run status is `running` or `starting`, it may still be in progress — wait and re-inspect.
- Compare `verification_result` against `evaluation` to understand whether the verifier and evaluator agree.

## Arguments

If the user passes a run ID after `/autodialectics:inspect`, inspect that run and summarize the results.
