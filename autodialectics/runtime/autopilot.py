"""Autonomous benchmark/evolution loop helpers."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AutopilotCycleReport:
    """Result for one autonomous benchmark/evolution cycle."""

    cycle_index: int
    started_at: str = field(default_factory=_utcnow_iso)
    ended_at: str = ""
    champion_policy_id: str = ""
    challenger_policy_id: str | None = None
    resulting_champion_policy_id: str = ""
    champion_run_ids: list[str] = field(default_factory=list)
    challenger_run_ids: list[str] = field(default_factory=list)
    champion_overall_score: float = 0.0
    champion_slop_composite: float = 0.0
    champion_canary_passed: bool = False
    champion_run_count: int = 0
    challenger_overall_score: float | None = None
    challenger_slop_composite: float | None = None
    challenger_canary_passed: bool | None = None
    challenger_run_count: int = 0
    promoted: bool = False
    promotion_outcome: str = "skipped"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutopilotSessionReport:
    """Aggregate report for an autonomous session."""

    session_id: str
    started_at: str = field(default_factory=_utcnow_iso)
    ended_at: str = ""
    status: str = "running"
    duration_seconds: float | None = None
    max_cycles: int | None = None
    sleep_seconds: int = 0
    failure_backoff_seconds: int = 0
    require_healthy_gateway: bool = False
    gateway_supervised: bool = False
    gateway_url: str | None = None
    total_cycles: int = 0
    successful_cycles: int = 0
    promoted_cycles: int = 0
    consecutive_failures: int = 0
    final_champion_policy_id: str = ""
    cycles: list[AutopilotCycleReport] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cycles"] = [cycle.as_dict() for cycle in self.cycles]
        return payload


class LocalGatewaySupervisor:
    """Keep a localhost CLI gateway reachable for unattended runs."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._process: subprocess.Popen[str] | None = None
        self._started_by_supervisor = False

    @property
    def managed(self) -> bool:
        return self._started_by_supervisor

    def health_url(self) -> str:
        parsed = urlparse(self.base_url)
        hostname = parsed.hostname or "127.0.0.1"
        if hostname == "0.0.0.0":
            hostname = "127.0.0.1"
        scheme = parsed.scheme or "http"
        port = parsed.port
        netloc = f"{hostname}:{port}" if port else hostname
        return f"{scheme}://{netloc}/health"

    def is_local(self) -> bool:
        parsed = urlparse(self.base_url)
        hostname = (parsed.hostname or "").lower()
        return hostname in {"127.0.0.1", "localhost", "0.0.0.0"}

    def is_healthy(self, timeout: float = 2.0) -> bool:
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(self.health_url())
                response.raise_for_status()
                return response.json().get("status") == "ok"
        except Exception:
            return False

    def ensure_available(
        self,
        *,
        startup_timeout: float = 20.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Start a local CLI gateway when needed and wait for health."""
        if self.is_healthy():
            return True
        if not self.is_local():
            return False

        if self._process is not None and self._process.poll() is not None:
            self._process = None
            self._started_by_supervisor = False

        if self._process is None:
            self._start_gateway()

        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if self.is_healthy():
                return True
            if self._process is not None and self._process.poll() is not None:
                break
            time.sleep(poll_interval)

        return self.is_healthy()

    def stop(self, timeout: float = 5.0) -> None:
        """Terminate a gateway started by this supervisor."""
        if not self._started_by_supervisor or self._process is None:
            return

        process = self._process
        self._process = None
        self._started_by_supervisor = False

        try:
            process.terminate()
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=timeout)
        except Exception:
            logger.debug("Failed to stop managed gateway cleanly", exc_info=True)

    def _start_gateway(self) -> None:
        parsed = urlparse(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        if host == "0.0.0.0":
            host = "127.0.0.1"
        port = parsed.port or 8644

        cmd = [
            sys.executable,
            "-m",
            "autodialectics.routing.cli_gateway",
            "--host",
            host,
            "--port",
            str(port),
        ]
        logger.info("Starting managed CLI gateway: %s", " ".join(cmd))
        self._process = subprocess.Popen(
            cmd,
            cwd=str(os.getcwd()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._started_by_supervisor = True
