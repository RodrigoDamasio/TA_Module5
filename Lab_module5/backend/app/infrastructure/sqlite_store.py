"""SQLite adapters: runs + events (atomic), memories, LLM response cache, Wikipedia cache,
settings. The only module with SQL; every value is a bound parameter."""

import json
import secrets
import threading
import time
from collections.abc import Callable

from app.domain.errors import RunNotFound
from app.domain.ports import Memory
from app.domain.run import ResearchRun, RunEvent, RunStatus, run_from_dict, run_to_dict

from . import database

_UPSERT_RUN = (
    "INSERT INTO runs (id, status, state_json, duration_ms, created_at, updated_at) "
    "VALUES (?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET status = excluded.status, state_json = excluded.state_json, "
    "duration_ms = excluded.duration_ms, updated_at = excluded.updated_at"
)
_INSERT_EVENT = "INSERT INTO events (run_id, type, data_json) VALUES (?, ?, ?)"
_GET_RUN = "SELECT state_json FROM runs WHERE id = ?"
_EVENTS_SINCE = "SELECT id, type, data_json FROM events WHERE run_id = ? AND id > ? ORDER BY id"
_RUNS_WITH_STATUS = "SELECT state_json FROM runs WHERE status = ?"
_OLD_RUNS = "SELECT id FROM runs WHERE updated_at < ? AND status IN (?, ?, ?)"
_DELETE_EVENTS = "DELETE FROM events WHERE run_id = ?"
_DELETE_RUN = "DELETE FROM runs WHERE id = ?"
_STATUS_COUNTS = "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
_DURATIONS = (
    "SELECT duration_ms FROM runs WHERE status = ? AND duration_ms IS NOT NULL "
    "ORDER BY updated_at DESC LIMIT ?"
)
_PUT_MEMORY = (
    "INSERT OR REPLACE INTO memories (run_id, task, summary, source_titles_json, created_at) "
    "VALUES (?, ?, ?, ?, ?)"
)
_RECENT_MEMORIES = "SELECT * FROM memories ORDER BY created_at DESC, rowid DESC LIMIT ?"
_DELETE_MEMORIES = "DELETE FROM memories WHERE created_at < ?"
_GET_CACHE = "SELECT response_json FROM llm_cache WHERE key = ?"
_PUT_CACHE = "INSERT OR REPLACE INTO llm_cache (key, response_json) VALUES (?, ?)"
_ALL_CACHE = "SELECT key, response_json FROM llm_cache"
_GET_WIKI = "SELECT response_json, fetched_at FROM wiki_cache WHERE key = ?"
_PUT_WIKI = "INSERT OR REPLACE INTO wiki_cache (key, response_json, fetched_at) VALUES (?, ?, ?)"
_GET_SETTING = "SELECT value FROM settings WHERE name = ?"
_PUT_SETTING = "INSERT OR IGNORE INTO settings (name, value) VALUES (?, ?)"


class _Store:
    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        database.init(path)

    def _conn(self):
        return database.connect(self._path)


class SqliteRunRepository(_Store):
    def create(self, run: ResearchRun) -> None:
        self.save(run)

    def save(self, run: ResearchRun) -> None:
        """Run state and its pending events in ONE transaction: the SSE stream and the stored
        state never disagree."""
        with self._lock, self._conn() as conn:
            events = run.pop_events()
            conn.execute(
                _UPSERT_RUN,
                (
                    run.id,
                    run.status.value,
                    json.dumps(run_to_dict(run)),
                    run.duration_ms,
                    run.created_at,
                    run.updated_at,
                ),
            )
            for event in events:
                cursor = conn.execute(_INSERT_EVENT, (run.id, event.type, json.dumps(event.data)))
                event.id = cursor.lastrowid

    def get(self, run_id: str) -> ResearchRun:
        with self._conn() as conn:
            row = conn.execute(_GET_RUN, (run_id,)).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return run_from_dict(json.loads(row["state_json"]))

    def events_since(self, run_id: str, after_id: int) -> list[RunEvent]:
        with self._conn() as conn:
            rows = conn.execute(_EVENTS_SINCE, (run_id, after_id)).fetchall()
        return [RunEvent(r["type"], json.loads(r["data_json"]), r["id"]) for r in rows]

    def runs_in(self, statuses: set[RunStatus]) -> list[ResearchRun]:
        with self._conn() as conn:
            rows = [
                r for s in sorted(statuses) for r in conn.execute(_RUNS_WITH_STATUS, (s.value,))
            ]
        return [run_from_dict(json.loads(r["state_json"])) for r in rows]

    def delete_older_than(self, cutoff_iso: str) -> int:
        """Retention: finished runs (and their events) not updated since the cutoff."""
        done = (RunStatus.COMPLETED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value)
        with self._lock, self._conn() as conn:
            ids = [r["id"] for r in conn.execute(_OLD_RUNS, (cutoff_iso, *done))]
            for run_id in ids:
                conn.execute(_DELETE_EVENTS, (run_id,))
                conn.execute(_DELETE_RUN, (run_id,))
        return len(ids)

    def status_counts(self) -> dict[str, int]:
        with self._conn() as conn:
            return {r["status"]: r["n"] for r in conn.execute(_STATUS_COUNTS)}

    def recent_durations_ms(self, limit: int) -> list[float]:
        with self._conn() as conn:
            rows = conn.execute(_DURATIONS, (RunStatus.COMPLETED.value, limit)).fetchall()
        return [float(r["duration_ms"]) for r in rows]


class SqliteMemoryRepository(_Store):
    def record(self, memory: Memory) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                _PUT_MEMORY,
                (
                    memory.run_id,
                    memory.task,
                    memory.summary,
                    json.dumps(memory.source_titles),
                    memory.created_at,
                ),
            )

    def recent(self, limit: int) -> list[Memory]:
        with self._conn() as conn:
            rows = conn.execute(_RECENT_MEMORIES, (limit,)).fetchall()
        return [
            Memory(
                r["run_id"],
                r["task"],
                r["summary"],
                json.loads(r["source_titles_json"]),
                r["created_at"],
            )
            for r in rows
        ]

    def delete_older_than(self, cutoff_iso: str) -> int:
        with self._lock, self._conn() as conn:
            return conn.execute(_DELETE_MEMORIES, (cutoff_iso,)).rowcount


class SqliteResponseCache(_Store):
    def get(self, key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(_GET_CACHE, (key,)).fetchone()
        return json.loads(row["response_json"]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_CACHE, (key, json.dumps(value)))

    def export(self) -> dict[str, dict]:
        with self._conn() as conn:
            rows = conn.execute(_ALL_CACHE).fetchall()
        return {r["key"]: json.loads(r["response_json"]) for r in rows}

    def seed(self, entries: dict[str, dict]) -> int:
        with self._lock, self._conn() as conn:
            conn.executemany(_PUT_CACHE, [(k, json.dumps(v)) for k, v in entries.items()])
        return len(entries)


class SqliteWikiCache(_Store):
    """Wikipedia responses by request key, with a time-to-live."""

    def __init__(self, path: str, clock: Callable[[], float] = time.time) -> None:
        super().__init__(path)
        self._clock = clock

    def get(self, key: str, max_age_s: float) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(_GET_WIKI, (key,)).fetchone()
        if row is None or self._clock() - row["fetched_at"] > max_age_s:
            return None
        return json.loads(row["response_json"])

    def put(self, key: str, value: dict) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_WIKI, (key, json.dumps(value), self._clock()))


class SqliteSettings(_Store):
    def prompt_secret(self, configured: str | None = None) -> bytes:
        """PROMPT_SECRET from the environment, else one generated at first start and kept
        in the database (so nonces, the canary and the cache survive restarts)."""
        if configured:
            return configured.encode()
        with self._lock, self._conn() as conn:
            conn.execute(_PUT_SETTING, ("prompt_secret", secrets.token_hex(32)))
            row = conn.execute(_GET_SETTING, ("prompt_secret",)).fetchone()
        return str(row["value"]).encode()
