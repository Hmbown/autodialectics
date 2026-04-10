from pathlib import Path
import json
import sqlite3
from typing import Any


class SqliteStore:
    """SQLite-backed persistence for runs, artifacts, policies, and benchmarks."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS run_manifests (
                run_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                run_id TEXT NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                PRIMARY KEY (run_id, name)
            );

            CREATE TABLE IF NOT EXISTS policies (
                policy_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS benchmark_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _dump(obj: Any) -> str:
        return json.dumps(obj, default=str, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Run manifests
    # ------------------------------------------------------------------
    def save_run_manifest(self, manifest: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO run_manifests (run_id, data) VALUES (?, ?)",
            (manifest["run_id"], self._dump(manifest)),
        )
        self.conn.commit()

    def get_run_manifest(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT data FROM run_manifests WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])

    # ------------------------------------------------------------------
    # Artifact paths
    # ------------------------------------------------------------------
    def save_artifact_path(self, run_id: str, name: str, path: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO artifacts (run_id, name, path) VALUES (?, ?, ?)",
            (run_id, name, path),
        )
        self.conn.commit()

    def get_artifact_paths(self, run_id: str) -> dict[str, str]:
        rows = self.conn.execute(
            "SELECT name, path FROM artifacts WHERE run_id = ?", (run_id,)
        ).fetchall()
        return {r["name"]: r["path"] for r in rows}

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def save_policy(self, policy: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO policies (policy_id, data) VALUES (?, ?)",
            (policy["policy_id"], self._dump(policy)),
        )
        self.conn.commit()

    def get_policy(self, policy_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT data FROM policies WHERE policy_id = ?", (policy_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data"])

    def latest_champion(self) -> dict | None:
        """Return the most recent policy where is_champion=True, or None."""
        rows = self.conn.execute(
            "SELECT data FROM policies ORDER BY rowid DESC"
        ).fetchall()
        for row in rows:
            data = json.loads(row["data"])
            if data.get("is_champion"):
                return data
        return None

    # ------------------------------------------------------------------
    # Benchmark reports
    # ------------------------------------------------------------------
    def save_benchmark_report(self, run_id: str, report: dict) -> None:
        self.conn.execute(
            "INSERT INTO benchmark_reports (run_id, data) VALUES (?, ?)",
            (run_id, self._dump(report)),
        )
        self.conn.commit()

    def recent_benchmark_reports(self) -> list[dict]:
        """Return the 10 most recent benchmark reports as dicts."""
        rows = self.conn.execute(
            "SELECT data FROM benchmark_reports ORDER BY id DESC LIMIT 10"
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    def benchmark_reports_for_run_ids(self, run_ids: list[str]) -> list[dict]:
        """Return benchmark reports for a specific set of run_ids."""
        if not run_ids:
            return []

        placeholders = ", ".join("?" for _ in run_ids)
        rows = self.conn.execute(
            (
                "SELECT run_id, data FROM benchmark_reports "
                f"WHERE run_id IN ({placeholders}) ORDER BY id DESC"
            ),
            tuple(run_ids),
        ).fetchall()

        reports = [json.loads(r["data"]) for r in rows]
        order = {run_id: index for index, run_id in enumerate(run_ids)}
        reports.sort(key=lambda report: order.get(report.get("run_id", ""), len(order)))
        return reports

    def close(self) -> None:
        self.conn.close()
