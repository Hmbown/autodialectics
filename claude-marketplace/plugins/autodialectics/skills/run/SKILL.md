---
name: run
description: Compile and execute an Autodialectics anti-slop pipeline for a task. Covers health checks, runtime init, contract compilation, and full pipeline execution.
---

# Autodialectics Run

Use this skill to drive the Autodialectics anti-slop pipeline against a task.

## Prerequisites

`autodialectics-mcp` must be on PATH (`pip install autodialectics`).

## MCP Workflow

1. **`health`** — verify the MCP server is reachable.
2. **`init_runtime`** — ensure the database and default champion policy exist.
3. **`compile_task`** — compile the task JSON into an immutable contract. Inspect it before proceeding.
4. **`run_task`** — execute the full pipeline (evidence → dialectic → execution → verification → evaluation → gate).
   - Pass `detach: true` for long-running tasks. Poll with `inspect_run` afterward.

## CLI Fallback

If the MCP server is not available:

```bash
autodialectics init
autodialectics compile <task.json>
autodialectics run <task.json>
```

## Task File Format

Tasks are JSON files. Only `title` is required; everything else has sensible defaults:

```json
{
  "title": "Short description",
  "description": "What needs to be done and why",
  "domain": "code|research|writing|experiment|analysis|generic",
  "objectives": ["What the task must achieve"],
  "constraints": ["Boundaries the solution must respect"],
  "deliverables": ["Concrete outputs expected"],
  "acceptance_criteria": ["How to judge success"],
  "forbidden_shortcuts": ["Approaches that are explicitly banned"],
  "workspace_root": "path/to/workspace",
  "verification_commands": ["pytest -q"],
  "max_repair_attempts": 3,
  "assets": [{"kind": "file", "location": "path/to/file", "label": "name"}]
}
```

## Pipeline Stages

`run_task` executes these stages in order, producing one artifact each:

1. **Compile** → `contract.md` — locks the task into an immutable contract
2. **Explore** → `evidence.json` — gathers evidence relevant to the task
3. **Plan (Dialectic)** → `dialectic.json` — thesis/antithesis/synthesis resolution
4. **Execute** → `execution.json` — domain-specific execution (code, research, writing, etc.)
5. **Verify** → `verification.json` — independent verification of execution results
6. **Evaluate** → `evaluation.json` — slop scoring and gate decision (accept/reject/revise/rollback)
7. **Summarize** → `summary.md` — human-readable run summary

## Guidance

- Always compile before running if the task is new or ambiguous.
- Summaries should include: run ID, decision (accept/reject/revise/rollback), overall score, slop composite, and unresolved risks.
- Pass a `policy_id` to `run_task` to test a specific policy instead of the current champion.

## Arguments

If the user passes a task path after `/autodialectics:run`, treat it as the target task file and execute the compile → run workflow.
