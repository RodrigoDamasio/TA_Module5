import sqlite3
from pathlib import Path

# Constant DDL — the only statements run through executescript (never built from input).
SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    state_json  TEXT NOT NULL,
    duration_ms INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_status ON runs (status);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    type        TEXT NOT NULL,
    data_json   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS events_by_run ON events (run_id, id);
CREATE TABLE IF NOT EXISTS memories (
    run_id      TEXT PRIMARY KEY,
    task        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    source_titles_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key           TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS wiki_cache (
    key           TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    fetched_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    name        TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init(path: str) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
