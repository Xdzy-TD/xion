from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

RSRP_BANDS = [
    (-70, float("inf"), "Excellent"),
    (-90, -70, "Good"),
    (-110, -90, "Fair"),
    (-120, -110, "Poor"),
    (float("-inf"), -120, "Very Poor"),
]


def rsrp_quality(value: float) -> str:
    for lo, hi, label in RSRP_BANDS:
        if lo <= value < hi:
            return label
    return "Unknown"


@dataclass
class SignalSummary:
    total_records: int
    analyzed_records: int
    average_rsrp: Optional[float]
    strongest_rsrp: Optional[float]
    strongest_cell: Optional[str]
    weakest_rsrp: Optional[float]
    weakest_cell: Optional[str]


def analyze_signal_strength(df: pd.DataFrame) -> SignalSummary:
    total = len(df)
    valid = df.dropna(subset=["rsrp"])
    if valid.empty:
        return SignalSummary(total, 0, None, None, None, None, None)

    max_row = valid.loc[valid["rsrp"].idxmax()]
    min_row = valid.loc[valid["rsrp"].idxmin()]
    return SignalSummary(
        total_records=total,
        analyzed_records=len(valid),
        average_rsrp=round(float(valid["rsrp"].mean()), 2),
        strongest_rsrp=float(max_row["rsrp"]),
        strongest_cell=str(max_row.get("cell_id")),
        weakest_rsrp=float(min_row["rsrp"]),
        weakest_cell=str(min_row.get("cell_id")),
    )


def network_type_distribution(df: pd.DataFrame) -> pd.Series:
    return df["radio_type"].fillna("Unknown").value_counts()


def top_cells_by_signal(df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    valid = df.dropna(subset=["rsrp", "cell_id"])
    if valid.empty:
        return pd.DataFrame(columns=["cell_id", "avg_rsrp", "samples"])
    grouped = (
        valid.groupby("cell_id")["rsrp"]
        .agg(avg_rsrp="mean", samples="count")
        .sort_values("avg_rsrp", ascending=False)
        .head(top_n)
        .reset_index()
    )
    grouped["avg_rsrp"] = grouped["avg_rsrp"].round(2)
    return grouped


def call_type_distribution(df: pd.DataFrame) -> pd.Series:
    return df["call_type"].fillna("UNKNOWN").value_counts()


# Pandas' offset aliases have shifted over time (e.g. calendar-month "M" was
# retired in favor of "ME"). Callers throughout the app (CLI + web app) still
# think and speak in the simple "D"/"W"/"M" shorthand, so translate here in
# one place rather than depending on whichever alias the installed pandas
# happens to still accept.
_FREQ_ALIASES = {"D": "D", "W": "W", "M": "ME"}


def time_series_trend(df: pd.DataFrame, freq: str = "D") -> pd.DataFrame:
    freq = _FREQ_ALIASES.get(freq, freq)
    valid = df.dropna(subset=["rsrp", "timestamp"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["period", "avg_rsrp", "samples"])
    valid["timestamp"] = pd.to_datetime(valid["timestamp"], errors="coerce")
    valid = valid.dropna(subset=["timestamp"])
    grouped = (
        valid.set_index("timestamp")["rsrp"]
        .resample(freq)
        .agg(["mean", "count"])
        .rename(columns={"mean": "avg_rsrp", "count": "samples"})
        .dropna()
        .reset_index()
        .rename(columns={"timestamp": "period"})
    )
    grouped["avg_rsrp"] = grouped["avg_rsrp"].round(2)
    return grouped


# Curated column sets for the drill-down tables in the CLI/web app. The raw
# records DataFrame also carries DB bookkeeping columns (id, profile_id,
# source_file, import_hash, profile_name, lac/mcc/mnc, ...) that just add
# noise to a focused "what triggered this anomaly" view, so both UIs share
# these lists rather than dumping every column.
WEAK_SIGNAL_DISPLAY_COLUMNS = ["timestamp", "phone_number", "cell_id", "radio_type", "rsrp"]
DURATION_OUTLIER_DISPLAY_COLUMNS = ["timestamp", "phone_number", "call_type", "cell_id", "duration"]


def display_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Return `df` narrowed to `columns`, skipping any that aren't present."""
    present = [c for c in columns if c in df.columns]
    return df[present] if present else df


def detect_duration_outliers(df: pd.DataFrame, multiplier: float = 3.0) -> pd.DataFrame:
    """Flag calls whose duration is far above this profile's own average.

    This is a *relative* check (unlike the fixed `long_call_seconds`
    threshold): a 10-minute call might be unremarkable for one person and
    a clear outlier for another, so the baseline is computed per-profile.

    The baseline only considers connected calls (duration > 0) so
    zero-duration missed/rejected entries don't drag it down and create
    false positives. Returns the actual outlier rows (not just a count)
    so callers can inspect/display them directly.
    """
    if df.empty or "duration" not in df.columns:
        return df.iloc[0:0]

    calls = df.copy()
    calls["duration"] = pd.to_numeric(calls["duration"], errors="coerce")
    calls = calls.dropna(subset=["duration"])
    calls = calls[calls["duration"] > 0]
    if len(calls) < 2:
        # Not enough data to establish a meaningful baseline.
        return calls.iloc[0:0]

    baseline = calls["duration"].mean()
    if not baseline or baseline <= 0:
        return calls.iloc[0:0]

    outliers = calls[calls["duration"] > baseline * multiplier]
    return outliers.sort_values("duration", ascending=False)


def weak_signal_readings(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Return the actual rows at or below the given RSRP threshold, weakest first.

    Complements `analyze_signal_strength`/`detect_anomalies`, which only
    report aggregate numbers — this exposes the specific readings so they
    can be drilled into (e.g. shown in a table or mapped).
    """
    if df.empty or "rsrp" not in df.columns:
        return df.iloc[0:0]

    valid = df.dropna(subset=["rsrp"])
    weak = valid[valid["rsrp"] <= threshold]
    return weak.sort_values("rsrp")


@dataclass
class Anomaly:
    kind: str
    detail: str
    severity: str


def detect_anomalies(df: pd.DataFrame, config) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    if df.empty:
        return anomalies

    valid_rsrp = df.dropna(subset=["rsrp"])
    poor = valid_rsrp[valid_rsrp["rsrp"] <= config.poor_signal_threshold_dbm]
    very_poor = valid_rsrp[valid_rsrp["rsrp"] <= config.very_poor_signal_threshold_dbm]
    if len(very_poor):
        anomalies.append(Anomaly(
            "signal", f"{len(very_poor)} record(s) at or below "
                      f"{config.very_poor_signal_threshold_dbm} dBm (very poor).",
            "critical"))
    elif len(poor):
        anomalies.append(Anomaly(
            "signal", f"{len(poor)} record(s) at or below "
                      f"{config.poor_signal_threshold_dbm} dBm (poor).",
            "warning"))

    long_calls = df[df["duration"].fillna(0) >= config.long_call_seconds]
    if len(long_calls):
        anomalies.append(Anomaly(
            "duration", f"{len(long_calls)} call(s) at or above "
                        f"{config.long_call_seconds}s.",
            "info"))

    duration_outliers = detect_duration_outliers(df, config.duration_outlier_multiplier)
    if len(duration_outliers):
        anomalies.append(Anomaly(
            "duration_outlier",
            f"{len(duration_outliers)} call(s) at least "
            f"{config.duration_outlier_multiplier}x longer than this profile's "
            f"average call.",
            "info"))

    missed = df[df["call_type"] == "MISSED"].dropna(subset=["timestamp", "phone_number"]).copy()
    if not missed.empty:
        missed["timestamp"] = pd.to_datetime(missed["timestamp"], errors="coerce")
        missed = missed.dropna(subset=["timestamp"]).sort_values("timestamp")
        window = pd.Timedelta(hours=config.missed_call_window_hours)
        for number, group in missed.groupby("phone_number"):
            times = group["timestamp"].tolist()
            for i in range(len(times)):
                count = sum(1 for t in times[i:] if t - times[i] <= window)
                if count >= config.missed_call_repeat_count:
                    anomalies.append(Anomaly(
                        "missed_calls",
                        f"{number}: {count} missed calls within "
                        f"{config.missed_call_window_hours}h.",
                        "warning"))
                    break
    return anomalies
