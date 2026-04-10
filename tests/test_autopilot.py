from __future__ import annotations

from autodialectics.runtime.autopilot import LocalGatewaySupervisor
from autodialectics.runtime.runner import RunRecord
from autodialectics.schemas import PolicySnapshot


def test_autopilot_runs_single_cycle_and_promotes(runtime, monkeypatch) -> None:
    champion = runtime.evolution.ensure_default_champion()
    benchmark_calls: list[str] = []
    evolve_reports: list[dict] = []

    def fake_benchmark(suite_dir=None, policy_id=None, **kwargs):
        assert policy_id is not None
        benchmark_calls.append(policy_id)

        policy_data = runtime.store.get_policy(policy_id)
        assert policy_data is not None
        score = 0.45 if policy_id == champion.policy_id else 0.70
        slop = 0.20 if policy_id == champion.policy_id else 0.10
        canary = 1.0
        policy_data["benchmark_summary"] = {
            "overall_score": score,
            "slop_composite": slop,
            "accepted_rate": 1.0,
            "run_count": 1.0,
            "canary_passed": canary,
        }
        runtime.store.save_policy(policy_data)

        run_id = f"{policy_id}_run"
        runtime.store.save_benchmark_report(
            run_id,
            {
                "run_id": run_id,
                "policy_id": policy_id,
                "submission": {"title": f"benchmark for {policy_id}"},
                "slop": {"composite": slop},
                "unmet_criteria": [],
                "notes": [],
            },
        )

        return [
            RunRecord(
                run_id=run_id,
                contract_id="contract",
                domain="analysis",
                policy_id=policy_id,
                status="completed",
                decision="accept",
                overall_score=score,
                slop_composite=slop,
            )
        ]

    def fake_evolve_from_reports(reports, *, use_gepa=True):
        evolve_reports.extend(reports)
        challenger = PolicySnapshot(
            parent_id=champion.policy_id,
            surfaces=dict(champion.surfaces),
            is_champion=False,
            generation="heuristic",
        )
        runtime.store.save_policy(challenger.model_dump(mode="json"))
        return challenger.policy_id

    monkeypatch.setattr(runtime, "benchmark", fake_benchmark)
    monkeypatch.setattr(runtime, "evolve_from_reports", fake_evolve_from_reports)

    report = runtime.autopilot(
        max_cycles=1,
        sleep_seconds=0,
        failure_backoff_seconds=0,
    )

    assert report.status == "max_cycles_reached"
    assert report.total_cycles == 1
    assert report.successful_cycles == 1
    assert report.promoted_cycles == 1
    assert len(report.cycles) == 1
    assert report.cycles[0].promoted is True
    assert benchmark_calls[0] == champion.policy_id
    assert benchmark_calls[1] == report.cycles[0].challenger_policy_id
    assert evolve_reports
    assert all(item["policy_id"] == champion.policy_id for item in evolve_reports)


def test_autopilot_stops_after_consecutive_failures(runtime, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime,
        "benchmark",
        lambda suite_dir=None, policy_id=None, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    report = runtime.autopilot(
        max_cycles=5,
        sleep_seconds=0,
        failure_backoff_seconds=0,
        max_consecutive_failures=2,
    )

    assert report.status == "consecutive_failures"
    assert report.total_cycles == 2
    assert report.successful_cycles == 0
    assert report.consecutive_failures == 2
    assert len(report.cycles) == 2
    assert all(cycle.error == "boom" for cycle in report.cycles)


def test_local_gateway_supervisor_health_url_normalizes_localhost() -> None:
    supervisor = LocalGatewaySupervisor("http://0.0.0.0:8642")

    assert supervisor.is_local() is True
    assert supervisor.health_url() == "http://127.0.0.1:8642/health"
