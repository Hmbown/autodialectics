# Overnight Agent Prompt: Pre-Mortem Failure Router

You are working in `/Volumes/VIXinSSD/autodialectics`.

Use the `autodialectics-repo` MCP server when useful. You may also work directly in the codebase.

Mission:

Investigate a high-upside idea for this repository:

Can we predict likely bad runs early, before spending full execution and verification cost, and use that prediction to route harder tasks into more scrutiny?

If this works, it could materially improve trustworthiness per unit of compute for agentic systems, which is a large upside bet and a good fit for Autodialectics.

Hypothesis:

Cheap signals available early in the pipeline, such as evidence coverage gaps, objection severity, contract complexity, missing verification commands, prior benchmark patterns, and early execution artifacts, may predict final rejection, high slop, or canary failure well enough to support an adaptive routing policy.

What to do:

1. Read the relevant code and docs first:
   - `README.md`
   - `docs/architecture.md`
   - `autodialectics/runtime/runner.py`
   - `autodialectics/evaluation/slop.py`
   - `autodialectics/dialectic/engine.py`
   - `autodialectics/storage/sqlite.py`

2. Inspect the available data sources:
   - `autodialectics.db`
   - `artifacts/run_*`
   - `artifacts/autopilot/*`
   - benchmark reports in SQLite

3. Define at least two concrete candidate predictors for bad outcomes.
   - Start with simple heuristics and lightweight statistical baselines.
   - Prefer stdlib and existing dependencies first.
   - Only add a new dependency if it is clearly justified by the experiment.

4. Build a reproducible experiment.
   - Create a script or module that extracts features from prior runs or benchmark reports.
   - Define labels such as reject vs accept, canary fail, or slop above threshold.
   - Measure whether the signal is actually predictive.
   - Use metrics that matter for routing decisions, not just raw accuracy.

5. Simulate an adaptive policy.
   - Compare baseline behavior against a routed policy that escalates scrutiny when the predictor fires.
   - Estimate both quality impact and compute cost impact.

6. If the result is promising, implement the smallest clean integration behind an explicit experimental flag.
   - Keep the change reversible.
   - Do not over-abstract.
   - Do not silently change default behavior unless the evidence is unusually strong.

7. If the result is not promising, do not force it.
   - Write a clear falsification memo.
   - Identify the best adjacent idea supported by the evidence.

Deliverables by the end of the run:

- A concise write-up of what you tried, what worked, what failed, and what you recommend next.
- Reproducible experiment code.
- Any minimal implementation changes needed for the best candidate.
- Tests for any shipped code changes.
- A final markdown summary at `artifacts/overnight_pre_mortem_router.md`.

Constraints:

- Work autonomously. Do not stop to ask questions unless you hit a hard blocker.
- Prefer evidence over theory.
- Prefer a strong negative result over a weak positive story.
- Do not promote a challenger policy unless benchmark evidence clearly supports it.
- Keep a high bar for claims.

Suggested success criteria:

- You find a predictor that is at least directionally useful for routing, or you produce a convincing falsification with a better next bet.
- The repo remains testable.
- The final summary is decision-useful, not just descriptive.
