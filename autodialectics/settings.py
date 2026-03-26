import os
from pathlib import Path

from pydantic import BaseModel


def _candidate_config_paths(config_path: str | None = None) -> list[Path]:
    candidates: list[Path] = []

    if config_path:
        candidates.append(Path(config_path).expanduser())
        return candidates

    env_path = os.getenv("AUTODIALECTICS_CONFIG")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.append(Path.cwd() / "autodialectics.yaml")

    xdg_config_home = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()
    candidates.append(xdg_config_home / "autodialectics" / "autodialectics.yaml")

    return candidates

class Settings(BaseModel):
    cliproxy_base_url: str = "http://127.0.0.1:8642"
    cliproxy_api_key: str = ""
    cliproxy_model: str = "default"
    db_path: str = "autodialectics.db"
    artifacts_dir: str = "artifacts"
    benchmark_dir: str = "benchmarks/cases"
    use_dspy_rlm: bool = False
    dspy_api_base: str | None = None
    dspy_api_key: str | None = None
    rlm_threshold_chars: int = 8000
    max_evidence_items: int = 20

    def role_candidates(self, role: str) -> list[str]:
        return []  # CLIProxyAPI role routing fills this

    @classmethod
    def load(cls, config_path: str | None = None) -> "Settings":
        import yaml

        for candidate in _candidate_config_paths(config_path):
            if not candidate.exists():
                continue

            data = yaml.safe_load(candidate.read_text())
            return cls(**(data or {}))

        return cls()

    @property
    def artifacts_path(self) -> Path:
        return Path(self.artifacts_dir)
