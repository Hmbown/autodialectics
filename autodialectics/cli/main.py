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


def _autopilot_output_paths(settings, session_id: str) -> tuple[Path, Path]:
    base = Path(settings.artifacts_dir) / "autopilot"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{session_id}.json", base / f"{session_id}.md"


def _render_autopilot_markdown(report) -> str:
    lines = [
        f"# Autopilot Session: {report.session_id}",
        "",
        f"- Status: {report.status}",
        f"- Started: {report.started_at}",
        f"- Ended: {report.ended_at}",
        f"- Total cycles: {report.total_cycles}",
        f"- Successful cycles: {report.successful_cycles}",
        f"- Promotions: {report.promoted_cycles}",
        f"- Final champion: {report.final_champion_policy_id or 'unknown'}",
    ]

    if report.gateway_url:
        lines.append(f"- Gateway URL: {report.gateway_url}")

    if report.notes:
        lines += ["", "## Notes", ""]
        for note in report.notes:
            lines.append(f"- {note}")

    if report.cycles:
        lines += ["", "## Cycles", ""]
        for cycle in report.cycles:
            lines.append(
                (
                    f"- Cycle {cycle.cycle_index}: champion={cycle.champion_policy_id} "
                    f"score={cycle.champion_overall_score:.2f} "
                    f"slop={cycle.champion_slop_composite:.2f} "
                    f"promotion={cycle.promotion_outcome} "
                    f"final_champion={cycle.resulting_champion_policy_id or 'unknown'}"
                )
            )
            if cycle.error:
                lines.append(f"  error: {cycle.error}")

    lines.append("")
    return "\n".join(lines)


def _persist_autopilot_report(settings, report) -> tuple[Path, Path]:
    json_path, md_path = _autopilot_output_paths(settings, report.session_id)
    json_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    md_path.write_text(_render_autopilot_markdown(report), encoding="utf-8")
    return json_path, md_path


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
    console.print(f"  Champion policy: {champion.policy_id}", soft_wrap=True)
    console.print(f"  DB: {settings.db_path}", soft_wrap=True)
    console.print(f"  Artifacts: {settings.artifacts_dir}", soft_wrap=True)


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


@app.command()
def autopilot(
    suite_dir: Optional[str] = typer.Option(None, help="Benchmark suite directory"),
    max_cycles: Optional[int] = typer.Option(None, help="Maximum benchmark/evolution cycles to run"),
    duration_hours: Optional[float] = typer.Option(
        None,
        help="Wall-clock runtime budget in hours. Defaults to 8 when neither bound is supplied.",
    ),
    sleep_seconds: int = typer.Option(300, help="Seconds to sleep between successful cycles"),
    failure_backoff_seconds: int = typer.Option(60, help="Seconds to sleep after a failed cycle"),
    max_consecutive_failures: int = typer.Option(3, help="Stop after this many consecutive failed cycles"),
    no_gepa: bool = typer.Option(False, "--no-gepa", help="Disable GEPA when evolving challengers"),
    ensure_gateway: bool = typer.Option(
        True,
        "--ensure-gateway/--no-ensure-gateway",
        help="Auto-start a local CLI gateway when cliproxy points at localhost and nothing is listening.",
    ),
    allow_heuristic_fallback: bool = typer.Option(
        False,
        "--allow-heuristic-fallback",
        help="Permit heuristic-only operation when no healthy LLM gateway is available.",
    ),
    pre_mortem_routing: bool = typer.Option(
        False,
        "--pre-mortem-routing",
        help="[Experimental] Enable pre-mortem failure router to skip or scrutinize likely-bad runs before execution.",
    ),
) -> None:
    """Run benchmark/evolution/promotion cycles unattended for an extended session."""
    settings = _load_settings()
    runtime = _get_runtime(settings)

    from autodialectics.runtime.autopilot import LocalGatewaySupervisor

    if max_cycles is None and duration_hours is None:
        duration_hours = 8.0

    duration_seconds = duration_hours * 3600 if duration_hours is not None else None
    gateway = None

    try:
        if ensure_gateway or not allow_heuristic_fallback:
            gateway = LocalGatewaySupervisor(settings.cliproxy_base_url)
            gateway_ready = (
                gateway.ensure_available() if ensure_gateway else gateway.is_healthy()
            )
            if not gateway_ready and not allow_heuristic_fallback:
                console.print(
                    "[red]No healthy LLM gateway is available for autonomous mode.[/red]"
                )
                raise typer.Exit(1)

        console.print("[bold blue]Starting autonomous overnight loop...[/bold blue]")
        report = runtime.autopilot(
            suite_dir=suite_dir,
            max_cycles=max_cycles,
            duration_seconds=duration_seconds,
            sleep_seconds=sleep_seconds,
            failure_backoff_seconds=failure_backoff_seconds,
            max_consecutive_failures=max_consecutive_failures,
            use_gepa=not no_gepa,
            before_cycle=(
                (lambda _cycle: gateway.ensure_available())
                if ensure_gateway and gateway
                else ((lambda _cycle: gateway.is_healthy()) if gateway else None)
            ),
            require_healthy_gateway=not allow_heuristic_fallback,
            gateway_supervised=bool(gateway and gateway.managed),
            gateway_url=settings.cliproxy_base_url if gateway else None,
            pre_mortem_routing=pre_mortem_routing,
        )
    finally:
        if gateway is not None:
            gateway.stop()

    json_path, md_path = _persist_autopilot_report(settings, report)

    table = Table(title="Autopilot Results")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Session", report.session_id)
    table.add_row("Status", report.status)
    table.add_row("Cycles", str(report.total_cycles))
    table.add_row("Successful", str(report.successful_cycles))
    table.add_row("Promotions", str(report.promoted_cycles))
    table.add_row("Final Champion", report.final_champion_policy_id or "unknown")
    table.add_row("JSON Report", str(json_path))
    table.add_row("Markdown Report", str(md_path))
    console.print(table)

    if report.notes:
        console.print(Panel("\n".join(report.notes), title="Autopilot Notes"))


if __name__ == "__main__":
    app()
