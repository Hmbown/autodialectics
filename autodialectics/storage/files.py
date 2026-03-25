from pathlib import Path

from autodialectics.utils.jsonio import save_json


class ArtifactStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        d = self.base / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_json(self, run_id: str, name: str, data) -> Path:
        p = self.run_dir(run_id) / name
        save_json(p, data.model_dump(mode="json") if hasattr(data, "model_dump") else data)
        return p

    def write_markdown(self, run_id: str, name: str, text: str) -> Path:
        p = self.run_dir(run_id) / name
        p.write_text(text, encoding="utf-8")
        return p
