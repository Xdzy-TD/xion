from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULTS = {
    "data_dir": "data",
    "reports_dir": "reports",
    "db_file": "data/xion.db",
    "poor_signal_threshold_dbm": -100.0,
    "very_poor_signal_threshold_dbm": -120.0,
    "long_call_seconds": 1800,
    "duration_outlier_multiplier": 3.0,
    "missed_call_repeat_count": 3,
    "missed_call_window_hours": 24,
    "report_interval": "manual",
    "default_export_format": "csv",
    "opencellid_api_key": None,
    "cell_location_csv": None,
}


@dataclass
class Config:
    data_dir: str = DEFAULTS["data_dir"]
    reports_dir: str = DEFAULTS["reports_dir"]
    db_file: str = DEFAULTS["db_file"]
    poor_signal_threshold_dbm: float = DEFAULTS["poor_signal_threshold_dbm"]
    very_poor_signal_threshold_dbm: float = DEFAULTS["very_poor_signal_threshold_dbm"]
    long_call_seconds: int = DEFAULTS["long_call_seconds"]
    duration_outlier_multiplier: float = DEFAULTS["duration_outlier_multiplier"]
    missed_call_repeat_count: int = DEFAULTS["missed_call_repeat_count"]
    missed_call_window_hours: int = DEFAULTS["missed_call_window_hours"]
    report_interval: str = DEFAULTS["report_interval"]
    default_export_format: str = DEFAULTS["default_export_format"]
    opencellid_api_key: str | None = DEFAULTS["opencellid_api_key"]
    cell_location_csv: str | None = DEFAULTS["cell_location_csv"]

    def abs_path(self, relative: str) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    def ensure_dirs(self) -> None:
        self.abs_path(self.data_dir).mkdir(parents=True, exist_ok=True)
        self.abs_path(self.reports_dir).mkdir(parents=True, exist_ok=True)
        self.abs_path(self.db_file).parent.mkdir(parents=True, exist_ok=True)


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        cfg = Config()
        save_config(cfg, path)
        return cfg

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    merged = {**DEFAULTS, **raw}
    cfg = Config(**{k: merged[k] for k in DEFAULTS})
    cfg.ensure_dirs()
    return cfg


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
    cfg.ensure_dirs()
