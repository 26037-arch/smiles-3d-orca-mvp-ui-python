from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"


class LocalSettings(BaseModel):
    orca_path: str | None = None
    demo_calculations: bool = True
    jobs_dir: str = str(DATA_DIR / "jobs")
    max_job_bytes: int = 2_000_000_000


def load_settings() -> LocalSettings:
    values: dict[str, object] = {}
    if SETTINGS_FILE.exists():
        try:
            values.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    if path := os.getenv("GEOORCA_ORCA_PATH"):
        values["orca_path"] = path
    if jobs := os.getenv("GEOORCA_JOBS_DIR"):
        values["jobs_dir"] = jobs
    if demo := os.getenv("GEOORCA_DEMO_CALCULATIONS"):
        values["demo_calculations"] = demo.lower() in {"1", "true", "yes"}
    return LocalSettings.model_validate(values)


def save_orca_path(path: str | None) -> LocalSettings:
    current = load_settings()
    current.orca_path = path
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(current.model_dump_json(indent=2), encoding="utf-8")
    return current


def configure_orca_environment(path: str | None) -> None:
    """Expose a validated ORCA install directory to OPI's binary resolver."""
    if not path:
        return
    directory = str(Path(path).resolve().parent)
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if directory.lower() not in {entry.lower() for entry in entries}:
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
