from pathlib import Path
import json


def load_json(path: Path) -> dict:
    """Load JSON from a file path."""
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> Path:
    """Save data as JSON to a file path. Returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path
