---
name: replay
description: Re-run a stored Autodialectics pipeline run, optionally with a different policy, to compare outcomes or debug regressions.
---

# Autodialectics Replay

Use this skill to replay a previous pipeline run with an optional policy override.

## Prerequisites

`autodialectics-mcp` must be on PATH (`pip install autodialectics`).

## MCP Tool

- **`replay_run(run_id, policy_id?)`** — re-execute a stored run manifest. If `policy_id` is provided, the replay uses that policy instead of the original.

## CLI Fallback

```bash
autodialectics replay <run_id>
autodialectics replay <run_id> --policy <policy_id>
```

## When to Replay

- **A/B policy comparison** — replay the same run with two different policies and compare decisions, scores, and slop composites.
- **Debugging a rejection** — replay a rejected run to see if the issue was the policy, the evidence, or the task itself.
- **Regression testing** — after evolving a policy, replay historical runs to check for regressions.

## Guidance

- Always `inspect_run` the original before replaying — understand what happened first.
- When comparing original vs replay, report both side by side: decision, overall score, slop composite, and any divergent artifact content.
- Replays create new run records — they don't overwrite the original.

## Arguments

If the user passes a run ID after `/autodialectics:replay`, replay that run and summarize the comparison with the original.
