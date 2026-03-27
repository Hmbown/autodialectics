---
description: Run the local Autodialectics benchmark suite and summarize the policy outcome
agent: build
---

Run the repository benchmark harness with `benchmark` when the MCP server is available, or `uv run autodialectics benchmark` as fallback.

Then:
- summarize total cases
- list any failures or rejected runs
- call out canary failures explicitly
- recommend whether `evolve_policy` or `uv run autodialectics evolve` is justified

If the user asked for deeper inspection, inspect the most relevant run IDs after the benchmark completes.
