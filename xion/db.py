from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id    INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    timestamp     TEXT,
    call_type     TEXT,
    phone_number  TEXT,
    duration      INTEGER,
    cell_id       TEXT,
    lac           TEXT,
    mcc           TEXT,
    mnc           TEXT,
    radio_type    TEXT,
    rsrp          REAL,
    source_file   TEXT,
    import_hash   TEXT UNIQUE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_profile ON records(profile_id);
CREATE INDEX IF NOT EXISTS idx_records_phone ON records(phone_number);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records(timestamp);

CREATE TABLE IF NOT EXISTS contacts (
    phone_number TEXT PRIMARY KEY,
    label        TEXT,
    notes        TEXT,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cell_locations (
    cell_key   TEXT PRIMARY KEY,
    lat        REAL,
    lon        REAL,
    source     TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

RECORD_COLUMNS = [
    "timestamp", "call_type", "phone_number", "duration", "cell_id",
    "lac", "mcc", "mnc", "radio_type", "rsrp",
]


@contextmanager
def connect(db_path: Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def get_or_create_profile(db_path: Path, name: str) -> int:
    with connect(db_path) as conn:
        cur = conn.execute("SELECT id FROM profiles WHERE name = ?", (name,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur = conn.execute("INSERT INTO profiles (name) VALUES (?)", (name,))
        return cur.lastrowid


def list_profiles(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(
            "SELECT p.id, p.name, p.created_at, COUNT(r.id) AS record_count "
            "FROM profiles p LEFT JOIN records r ON r.profile_id = p.id "
            "GROUP BY p.id ORDER BY p.name"
        ).fetchall()


def delete_profile(db_path: Path, name: str) -> bool:
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM profiles WHERE name = ?", (name,))
        return cur.rowcount > 0


def _row_hash(profile_id: int, row: pd.Series) -> str:
    key = "|".join(str(row.get(c, "")) for c in
                    ["timestamp", "phone_number", "call_type", "cell_id", "duration"])
    return hashlib.sha256(f"{profile_id}|{key}".encode("utf-8")).hexdigest()


def insert_records(db_path: Path, profile_id: int, df: pd.DataFrame,
                    source_file: str = "") -> tuple[int, int]:
    if df.empty:
        return 0, 0

    inserted, skipped = 0, 0
    with connect(db_path) as conn:
        for _, row in df.iterrows():
            h = _row_hash(profile_id, row)
            values = [row.get(c) for c in RECORD_COLUMNS]
            try:
                conn.execute(
                    f"INSERT INTO records (profile_id, {', '.join(RECORD_COLUMNS)}, "
                    f"source_file, import_hash) VALUES (?, {', '.join(['?'] * len(RECORD_COLUMNS))}, ?, ?)",
                    [profile_id, *values, source_file, h],
                )
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1
    return inserted, skipped


def fetch_records(db_path: Path, profile_id: Optional[int] = None) -> pd.DataFrame:
    with connect(db_path) as conn:
        if profile_id is None:
            query = ("SELECT r.*, p.name AS profile_name FROM records r "
                      "JOIN profiles p ON p.id = r.profile_id")
            df = pd.read_sql_query(query, conn)
        else:
            df = pd.read_sql_query(
                "SELECT r.*, p.name AS profile_name FROM records r "
                "JOIN profiles p ON p.id = r.profile_id WHERE r.profile_id = ?",
                conn, params=(profile_id,))
    return df


def upsert_contact(db_path: Path, phone_number: str, label: str = "", notes: str = "") -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO contacts (phone_number, label, notes, updated_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(phone_number) DO UPDATE SET "
            "label = excluded.label, notes = excluded.notes, updated_at = datetime('now')",
            (phone_number, label, notes),
        )


def get_contacts(db_path: Path) -> pd.DataFrame:
    with connect(db_path) as conn:
        return pd.read_sql_query("SELECT * FROM contacts ORDER BY label", conn)


def cache_cell_location(db_path: Path, cell_key: str, lat: float, lon: float, source: str) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO cell_locations (cell_key, lat, lon, source, updated_at) "
            "VALUES (?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(cell_key) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, "
            "source=excluded.source, updated_at=datetime('now')",
            (cell_key, lat, lon, source),
        )


def get_cached_cell_locations(db_path: Path) -> pd.DataFrame:
    with connect(db_path) as conn:
        return pd.read_sql_query("SELECT * FROM cell_locations", conn)


def get_meta(db_path: Path, key: str) -> Optional[str]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_meta(db_path: Path, key: str, value: str) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
