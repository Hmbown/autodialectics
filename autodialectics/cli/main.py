"""Autodialectics CLI: command-line interface for the pipeline."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from autodialectics.schemas import TaskSubmission

app = typer.Typer(
    name="autodialectics",
    help="Anti-slop agentic operating system",
    no_args_is_help=True,
)
console = Console()


def _load_settings() -> "Settings":
    from autodialectics.settings import Settings

    config_path = None
    ctx = click.get_current_context(silent=True)
    if ctx is not None:
        config_path = (ctx.obj or {}).get("config_path")

    return Settings.load(config_path)


@app.callback()
def main(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to a config file. Defaults to AUTODIALECTICS_CONFIG, ./autodialectics.yaml, or ~/.config/autodialectics/autodialectics.yaml.",
    ),
) -> None:
    ctx.obj = {"config_path": str(config) if config else None}


def _load_task_file(path: str) -> TaskSubmission:
    """Load a TaskSubmission from a JSON file."""
    p = Path(path)
    if not p.exists():
        console.print(f"[red]Task file not found:[/red] {path}")
        raise typer.Exit(1)
    data = json.loads(p.read_text(encoding="utf-8"))
    return TaskSubmission(**data)


def _get_runtime(settings=None):
    """Create a runtime instance."""
    if settings is None:
        settings = _load_settings()
    from autodialectics.runtime.runner import AutodialecticsRuntime

    return AutodialecticsRuntime(settings)


# ── run ─────────────────────────────────────────────────────────────


@app.command()
def run(
    task_file: Path = typer.Argument(..., help="Path to task JSON file"),
    policy_id: Optional[str] = typer.Option(None, help="Policy ID to use"),
) -> None:
    """Execute a full pipeline run."""
    settings = _load_settings()
    submission = _load_task_file(str(task_file))
    runtime = _get_runtime(settings)

    console.print(f"[bold blue]Starting run for:[/bold blue] {submission.title}")
    record = runtime.run(submission, policy_id=policy_id)

    if record.error:
        console.print(f"[red]Run failed:[/red] {record.error}")
        raise typer.Exit(1)

    table = Table(title="Run Results")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Run ID", record.run_id)
    table.add_row("Domain", record.domain)
    table.add_row("Status", record.status)
    table.add_row("Decision", record.decision or "N/A")
    table.add_row("Overall Score", f"{record.overall_score:.2f}")
    table.add_row("Slop Composite", f"{record.slop_composite:.2f}")
    console.print(table)

    if record.summary:
        console.print(Panel(record.summary, title="Summary"))


# ── compile ─────────────────────────────────────────────────────────


@app.command()
def compile(
    task_file: Path = typer.Argument(..., help="Path to task JSON file"),
) -> None:
    """Compile a task submission into a contract."""
    settings = _load_settings()
    submission = _load_task_file(str(task_file))
    runtime = _get_runtime(settings)

    contract = runtime.compile_task(submission)
    console.print(Panel(contract.to_markdown(), title="Task Contract"))


# ── benchmark ───────────────────────────────────────────────────────


@app.command()
def benchmark(
    suite_dir: Optional[str] = typer.Option(None, help="Benchmark suite directory"),
    policy_id: Optional[str] = typer.Option(None, help="Policy ID to use"),
) -> None:
    """Run the benchmark suite."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    console.print("[bold blue]Running benchmark suite...[/bold blue]")
    records = runtime.benchmark(suite_dir=suite_dir, policy_id=policy_id)

    if not records:
        console.print("[yellow]No benchmark cases found.[/yellow]")
        return

    table = Table(title="Benchmark Results")
    table.add_column("Run ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Score", style="green")
    table.add_column("Slop", style="red")
    table.add_column("Decision", style="yellow")

    for r in records:
        table.add_row(
            r.run_id,
            r.status,
            f"{r.overall_score:.2f}",
            f"{r.slop_composite:.2f}",
            r.decision or "N/A",
        )

    console.print(table)
    console.print(f"[bold]Total cases:[/bold] {len(records)}")


# ── evolve ──────────────────────────────────────────────────────────


@app.command()
def evolve(
    no_gepa: bool = typer.Option(False, "--no-gepa", help="Disable GEPA optimization"),
) -> None:
    """Create a challenger policy via evolution."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    use_gepa = not no_gepa
    policy_id = runtime.evolve(use_gepa=use_gepa)

    if not policy_id:
        console.print("[yellow]No benchmark reports available for evolution.[/yellow]")
        return

    console.print(f"[bold green]Created challenger policy:[/bold green] {policy_id}")


# ── promote ─────────────────────────────────────────────────────────


@app.command()
def promote(
    policy_id: str = typer.Argument(..., help="Policy ID to promote"),
) -> None:
    """Promote a challenger policy to champion."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    result = runtime.promote(policy_id)
    if result is None:
        console.print(f"[red]Promotion denied or policy not found:[/red] {policy_id}")
        raise typer.Exit(1)

    console.print(f"[bold green]Policy promoted:[/bold green] {policy_id}")


# ── rollback ────────────────────────────────────────────────────────


@app.command()
def rollback() -> None:
    """Rollback to the previous champion policy."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    policy_id = runtime.rollback()
    console.print(f"[bold green]Rolled back to champion:[/bold green] {policy_id}")


# ── inspect ─────────────────────────────────────────────────────────


@app.command()
def inspect(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
) -> None:
    """Print detailed info about a run."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    info = runtime.inspect(run_id)
    if info is None:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise typer.Exit(1)

    manifest = info.get("manifest", {})
    artifact_paths = info.get("artifact_paths", {})

    table = Table(title=f"Run: {run_id}")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    for key, value in manifest.items():
        table.add_row(str(key), str(value))
    console.print(table)

    if artifact_paths:
        console.print("\n[bold]Artifacts:[/bold]")
        for name, path in artifact_paths.items():
            console.print(f"  {name}: {path}")


# ── replay ──────────────────────────────────────────────────────────


@app.command()
def replay(
    run_id: str = typer.Argument(..., help="Run ID to replay"),
    policy_id: Optional[str] = typer.Option(None, help="Policy ID to use"),
) -> None:
    """Replay a run with a potentially different policy."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    record = runtime.replay(run_id, policy_id=policy_id)
    if record is None:
        console.print(f"[red]Run not found:[/red] {run_id}")
        raise typer.Exit(1)

    console.print(f"[bold blue]Replayed run:[/bold blue] {run_id}")
    if record.summary:
        console.print(Panel(record.summary))


# ── init ────────────────────────────────────────────────────────────


@app.command()
def init() -> None:
    """Initialize the database and create a default champion policy."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    champion = runtime.evolution.ensure_default_champion()
    console.print(f"[bold green]Initialized.[/bold green]")
    console.print(f"  Champion policy: {champion.policy_id}")
    console.print(f"  DB: {settings.db_path}")
    console.print(f"  Artifacts: {settings.artifacts_dir}")


# ── serve ───────────────────────────────────────────────────────────


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
) -> None:
    """Start the API server."""
    import uvicorn

    ctx = click.get_current_context(silent=True)
    config_path = (ctx.obj or {}).get("config_path") if ctx is not None else None
    if config_path:
        os.environ["AUTODIALECTICS_CONFIG"] = str(config_path)

    console.print(f"[bold blue]Starting server on {host}:{port}[/bold blue]")
    uvicorn.run(
        "autodialectics.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
