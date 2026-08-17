from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

COLUMN_ALIASES = {
    "signal_strength": "rsrp",
    "rsrp_dbm": "rsrp",
    "number": "phone_number",
    "phone": "phone_number",
    "type": "call_type",
    "cellid": "cell_id",
}

REQUIRED_COLUMNS = ["timestamp", "phone_number"]
KNOWN_COLUMNS = [
    "timestamp", "call_type", "phone_number", "duration", "cell_id",
    "lac", "mcc", "mnc", "radio_type", "rsrp",
]


class ImportError_(Exception):
    pass


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: c.strip().lower() for c in df.columns})
    df = df.rename(columns=COLUMN_ALIASES)

    # Two source columns can legitimately map to the same normalized name
    # (e.g. an export with both "number" and "phone"). Left un-deduped, that
    # produces a DataFrame with a *duplicate* column label, and every later
    # `df["phone_number"]` lookup then returns a two-column DataFrame instead
    # of a Series, which crashes the very first `.str.strip()` call on it.
    # Coalesce duplicates left-to-right (first non-null value wins) instead.
    if df.columns.duplicated().any():
        coalesced = {}
        for name in df.columns.unique():
            block = df.loc[:, df.columns == name]
            if isinstance(block, pd.DataFrame) and block.shape[1] > 1:
                coalesced[name] = block.bfill(axis=1).iloc[:, 0]
            else:
                coalesced[name] = df[name]
        df = pd.DataFrame(coalesced)

    for col in KNOWN_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[KNOWN_COLUMNS]


def load_data(file_path: str) -> pd.DataFrame:
    path = Path(file_path)
    if not path.exists():
        raise ImportError_(f"File not found: {file_path}")

    ext = path.suffix.lower().lstrip(".")
    try:
        if ext == "csv":
            # Read every column as text. Left to its own type inference,
            # pandas treats a numeric-looking phone number column (most of
            # them, worldwide) as an int/float column -- silently dropping
            # a leading "+" on every row, and worse, corrupting the *whole*
            # column into "9198000000.0"-style values the moment any single
            # row has a blank entry (e.g. an unknown caller). Reading as str
            # keeps phone numbers (and cell/lac/mcc/mnc identifiers, which
            # can have meaningful leading zeros) exactly as exported; the
            # genuinely numeric fields (rsrp, duration) are still coerced
            # with pd.to_numeric a few lines down.
            df = pd.read_csv(path, dtype=str)
        elif ext == "json":
            df = pd.read_json(path, dtype=str)
        else:
            raise ImportError_(f"Unsupported file format '{ext}'. Use CSV or JSON.")
    except (pd.errors.ParserError, ValueError) as e:
        raise ImportError_(f"Error reading {file_path}: {e}") from e

    if df.empty:
        raise ImportError_(f"No data found in {file_path}")

    df = _normalize_columns(df)

    missing_required = [c for c in REQUIRED_COLUMNS if df[c].isna().all()]
    if missing_required:
        raise ImportError_(
            f"{file_path} is missing required column(s): {', '.join(missing_required)}"
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["rsrp"] = pd.to_numeric(df["rsrp"], errors="coerce")
    df["duration"] = pd.to_numeric(df["duration"], errors="coerce").fillna(0).astype(int)

    # Missing/blank call types must stay genuinely blank. Casting a real NaN
    # to str gives "nan", but a column that never existed in the source file
    # (added as Python `None` in _normalize_columns) casts to the *different*
    # string "None" -- left unhandled, that literal word "NONE" used to leak
    # into the UI as if it were a real call type. Normalize both to blank.
    df["call_type"] = df["call_type"].fillna("").astype(str).str.strip().str.upper()
    df["call_type"] = df["call_type"].replace({"NAN": "", "NONE": ""}).replace("", None)

    # Same issue for phone numbers: a fully-missing column would otherwise
    # render as the literal text "None" instead of an empty value.
    df["phone_number"] = df["phone_number"].fillna("").astype(str).str.strip()
    df["phone_number"] = df["phone_number"].replace({"None": "", "nan": ""})

    df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df


def batch_load(file_paths: Iterable[str]) -> tuple[pd.DataFrame, list[str]]:
    frames = []
    errors: list[str] = []
    for fp in file_paths:
        try:
            frames.append(load_data(fp))
        except ImportError_ as e:
            errors.append(str(e))

    if not frames:
        return pd.DataFrame(columns=KNOWN_COLUMNS), errors

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(
        subset=["timestamp", "phone_number", "call_type", "cell_id", "duration"]
    )
    dropped_in_memory = before - len(combined)
    if dropped_in_memory:
        errors.append(f"[info] Dropped {dropped_in_memory} exact duplicate row(s) across the batch.")
    return combined, errors
