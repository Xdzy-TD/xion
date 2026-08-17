from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from . import db


def cell_key(row: pd.Series) -> str:
    return f"{row.get('mcc','')}-{row.get('mnc','')}-{row.get('lac','')}-{row.get('cell_id','')}"


def cell_signal_table(df: pd.DataFrame) -> pd.DataFrame:
    valid = df.dropna(subset=["rsrp"]).copy()
    if valid.empty:
        return pd.DataFrame(columns=["cell_key", "cell_id", "avg_rsrp", "samples"])
    valid["cell_key"] = valid.apply(cell_key, axis=1)
    grouped = (
        valid.groupby(["cell_key", "cell_id"])["rsrp"]
        .agg(avg_rsrp="mean", samples="count")
        .reset_index()
        .sort_values("avg_rsrp", ascending=False)
    )
    grouped["avg_rsrp"] = grouped["avg_rsrp"].round(2)
    return grouped


def load_location_csv(csv_path: str) -> dict[str, tuple[float, float]]:
    p = Path(csv_path)
    if not p.exists():
        return {}
    lookup_df = pd.read_csv(p)
    required = {"cell_key", "lat", "lon"}
    if not required.issubset(lookup_df.columns):
        raise ValueError(f"cell_location_csv must have columns: {sorted(required)}")
    return {row["cell_key"]: (row["lat"], row["lon"]) for _, row in lookup_df.iterrows()}


def resolve_locations(db_path: Path, cell_keys: list[str], config) -> dict[str, tuple[float, float]]:
    resolved: dict[str, tuple[float, float]] = {}

    cached = db.get_cached_cell_locations(db_path)
    for _, row in cached.iterrows():
        if row["cell_key"] in cell_keys:
            resolved[row["cell_key"]] = (row["lat"], row["lon"])

    remaining = [k for k in cell_keys if k not in resolved]
    if remaining and config.cell_location_csv:
        csv_lookup = load_location_csv(config.cell_location_csv)
        for k in remaining:
            if k in csv_lookup:
                lat, lon = csv_lookup[k]
                resolved[k] = (lat, lon)
                db.cache_cell_location(db_path, k, lat, lon, source="user_csv")

    remaining = [k for k in cell_keys if k not in resolved]
    if remaining and config.opencellid_api_key:
        resolved.update(_lookup_via_api(db_path, remaining, config.opencellid_api_key))

    return resolved


def _lookup_via_api(db_path: Path, cell_keys: list[str], api_key: str) -> dict[str, tuple[float, float]]:
    try:
        import requests
    except ImportError:
        return {}

    found: dict[str, tuple[float, float]] = {}
    for key in cell_keys:
        try:
            mcc, mnc, lac, cid = key.split("-")
            resp = requests.get(
                "https://opencellid.org/cell/get",
                params={"key": api_key, "mcc": mcc, "mnc": mnc, "lac": lac,
                        "cellid": cid, "format": "json"},
                timeout=5,
            )
            if resp.ok:
                payload = resp.json()
                lat, lon = payload.get("lat"), payload.get("lon")
                if lat and lon:
                    found[key] = (lat, lon)
                    db.cache_cell_location(db_path, key, lat, lon, source="opencellid")
        except Exception:
            continue
    return found


def build_coverage_map(df: pd.DataFrame, db_path: Path, config, out_path: Path) -> Optional[Path]:
    table = cell_signal_table(df)
    if table.empty:
        return None

    keys = table["cell_key"].tolist()
    locations = resolve_locations(db_path, keys, config)
    if not locations:
        return None

    try:
        import folium
    except ImportError:
        return None

    from .analysis import rsrp_quality
    color_by_quality = {
        "Excellent": "green", "Good": "lightgreen", "Fair": "orange",
        "Poor": "red", "Very Poor": "darkred", "Unknown": "gray",
    }

    lats = [loc[0] for loc in locations.values()]
    lons = [loc[1] for loc in locations.values()]
    center = (sum(lats) / len(lats), sum(lons) / len(lons))
    fmap = folium.Map(location=center, zoom_start=12)

    for _, row in table.iterrows():
        loc = locations.get(row["cell_key"])
        if not loc:
            continue
        quality = rsrp_quality(row["avg_rsrp"])
        folium.CircleMarker(
            location=loc,
            radius=6 + min(row["samples"], 20) / 4,
            popup=f"Cell {row['cell_id']}<br>Avg RSRP: {row['avg_rsrp']} dBm "
                  f"({quality})<br>Samples: {row['samples']}",
            color=color_by_quality.get(quality, "blue"),
            fill=True, fill_opacity=0.7,
        ).add_to(fmap)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(out_path))
    return out_path
