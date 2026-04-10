---
name: benchmark
description: Run benchmark suites and manage policy evolution — create challengers, compare against champions, promote or rollback policies.
---

# Autodialectics Benchmark & Evolve

Use this skill to benchmark policies and drive champion/challenger evolution.

## Prerequisites

`autodialectics-mcp` must be on PATH (`pip install autodialectics`).

## MCP Workflow

### Benchmarking

1. **`benchmark(suite_dir?, policy_id?)`** — run the benchmark suite against a policy. Returns case-by-case results with scores and decisions.

### Policy Evolution

2. **`evolve_policy(use_gepa?)`** — analyze recent benchmark reports and create a challenger policy. Set `use_gepa: false` to skip the GEPA optimizer (simpler heuristic fallback).
3. **`promote_policy(policy_id)`** — promote a challenger to champion if comparison rules allow.
4. **`rollback_policy()`** — revert to the previous champion if the current one regresses.

## CLI Fallback

```bash
autodialectics benchmark
autodialectics evolve
autodialectics promote <policy_id>
autodialectics rollback
```

## Typical Evolution Cycle

```
benchmark → evolve_policy → benchmark (with challenger) → compare → promote or rollback
```

1. Run benchmarks with the current champion to establish a baseline.
2. Evolve a challenger from the benchmark reports.
3. Run the same benchmarks with the challenger's policy ID.
4. Compare results. Promote if the challenger wins; rollback if it regresses.

## Guidance

- Never claim a policy is better without benchmark evidence from the same suite.
- When reporting benchmark results, include: total cases, pass/fail/revise counts, mean overall score, mean slop composite.
- If `evolve_policy` returns `no_reports`, run benchmarks first to generate data.
- Promotion can be denied by comparison rules — check the response status.

## Arguments

If the user passes a suite directory after `/autodialectics:benchmark`, use it as the benchmark suite path.
