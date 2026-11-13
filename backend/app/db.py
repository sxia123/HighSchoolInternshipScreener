"""Database abstraction supporting local SQLite and Turso (libSQL) Hrana HTTP."""

from __future__ import annotations

import base64
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

import httpx

from app.config import Settings
from app.http_client import build_http_client


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    rowcount: int = 0
    lastrowid: int | None = None


class Database(Protocol):
    backend_name: str

    def execute(self, sql: str, params: Sequence[Any] = ()) -> QueryResult: ...
    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> None: ...
    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None: ...
    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...
    def close(self) -> None: ...


class SqliteDatabase:
    """Local SQLite database using Python's built-in sqlite3 module."""

    backend_name = "sqlite"

    def __init__(self, db_path: str | Path) -> None:
        path_str = str(db_path)
        if path_str != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path_str, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")
        if path_str != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL;")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> QueryResult:
        cur = self._conn.execute(sql, tuple(params))
        self._conn.commit()
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []
        return QueryResult(
            rows=rows,
            rowcount=cur.rowcount,
            lastrowid=cur.lastrowid,
        )

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> None:
        self._conn.executemany(sql, [tuple(p) for p in seq_of_params])
        self._conn.commit()

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cur = self._conn.execute(sql, tuple(params))
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = self._conn.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()


def normalize_turso_http_url(url: str) -> str:
    """Convert a libsql:// or https:// Turso URL into its /v2/pipeline HTTP endpoint."""
    cleaned = url.strip().rstrip("/")
    if cleaned.startswith("libsql://"):
        cleaned = "https://" + cleaned[len("libsql://") :]
    elif not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    if cleaned.endswith("/v2/pipeline"):
        return cleaned
    return f"{cleaned}/v2/pipeline"


def encode_hrana_arg(value: Any) -> dict[str, Any]:
    """Encode a Python value into a Turso Hrana v2 tagged value object."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return {"type": "null"}
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def decode_hrana_cell(cell: dict[str, Any]) -> Any:
    """Decode a Turso Hrana v2 cell object back into a native Python value."""
    cell_type = cell.get("type")
    if cell_type == "null":
        return None
    if cell_type == "integer":
        return int(cell["value"])
    if cell_type == "float":
        return float(cell["value"])
    if cell_type == "blob":
        return base64.b64decode(cell["base64"])
    return cell.get("value")


def _parse_hrana_execute_result(item: dict[str, Any]) -> QueryResult:
    if item.get("type") != "ok":
        err = item.get("error", {})
        raise RuntimeError(f"Turso SQL error: {err.get('message', item)}")
    result = item["response"]["result"]
    cols = [col["name"] for col in result.get("cols", [])]
    rows: list[dict[str, Any]] = []
    for raw_row in result.get("rows", []):
        rows.append({cols[idx]: decode_hrana_cell(raw_row[idx]) for idx in range(len(cols))})
    last_id = result.get("last_insert_rowid")
    return QueryResult(
        rows=rows,
        rowcount=int(result.get("affected_row_count") or 0),
        lastrowid=int(last_id) if last_id is not None else None,
    )


class TursoHttpDatabase:
    """Turso (libSQL) client over the Hrana v2 HTTP pipeline API (pure Python)."""

    backend_name = "turso"

    def __init__(
        self,
        database_url: str,
        auth_token: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.endpoint = normalize_turso_http_url(database_url)
        self._owns_client = client is None
        self._client = client or build_http_client(
            timeout=20.0,
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            },
        )

    def _pipeline(self, statements: list[tuple[str, Sequence[Any]]]) -> list[QueryResult]:
        requests_payload: list[dict[str, Any]] = []
        for sql, params in statements:
            requests_payload.append(
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": [encode_hrana_arg(p) for p in params],
                    },
                }
            )
        requests_payload.append({"type": "close"})

        response = self._client.post(self.endpoint, json={"requests": requests_payload})
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results", [])
        # Exclude trailing close response when mapping 1:1 to input statements.
        return [_parse_hrana_execute_result(raw_results[i]) for i in range(len(statements))]

    def execute(self, sql: str, params: Sequence[Any] = ()) -> QueryResult:
        return self._pipeline([(sql, params)])[0]

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]) -> None:
        batch = [(sql, params) for params in seq_of_params]
        if not batch:
            return
        # Chunk large batches to keep HTTP payloads compact.
        chunk_size = 50
        for start in range(0, len(batch), chunk_size):
            self._pipeline(batch[start : start + chunk_size])

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        res = self.execute(sql, params)
        return res.rows[0] if res.rows else None

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return self.execute(sql, params).rows

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS internships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dedup_key TEXT NOT NULL UNIQUE,
        external_id TEXT,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        location TEXT NOT NULL DEFAULT '',
        latitude REAL,
        longitude REAL,
        work_mode TEXT NOT NULL DEFAULT 'unspecified',
        apply_url TEXT NOT NULL,
        source_url TEXT,
        source_type TEXT NOT NULL,
        source_label TEXT NOT NULL,
        description_text TEXT NOT NULL DEFAULT '',
        posted_at TEXT,
        deadline TEXT,
        eligibility_status TEXT NOT NULL,
        eligibility_score INTEGER NOT NULL DEFAULT 0,
        evidence_quote TEXT NOT NULL DEFAULT '',
        rejection_reason TEXT NOT NULL DEFAULT '',
        grade_or_age TEXT NOT NULL DEFAULT '',
        compensation TEXT NOT NULL DEFAULT 'unspecified',
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_internships_status ON internships(eligibility_status)",
    "CREATE INDEX IF NOT EXISTS idx_internships_last_seen ON internships(last_seen_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        source_type TEXT NOT NULL,
        target TEXT NOT NULL,
        area_hint TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_scanned_at TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE(source_type, target)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS geocode_cache (
        query_norm TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        cached_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        trigger TEXT NOT NULL,
        sources_scanned INTEGER NOT NULL DEFAULT 0,
        fetched_count INTEGER NOT NULL DEFAULT 0,
        upserted_count INTEGER NOT NULL DEFAULT 0,
        eligible_count INTEGER NOT NULL DEFAULT 0,
        possible_count INTEGER NOT NULL DEFAULT 0,
        rejected_count INTEGER NOT NULL DEFAULT 0,
        errors_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


def init_schema(db: Database) -> None:
    """Create database tables and indexes if they do not exist."""
    for stmt in SCHEMA_STATEMENTS:
        db.execute(stmt)


def _source_key(source_type: str, target: str) -> str:
    return f"{source_type}:{target}"


def seed_default_sources(db: Database, sources_file: Path) -> int:
    """Seed new entries from sources.json once per unique (source_type, target) key."""
    if not sources_file.is_file():
        return 0
    entries = json.loads(sources_file.read_text(encoding="utf-8"))

    seeded_meta = db.fetchone("SELECT value FROM app_meta WHERE key = 'seeded_source_keys'")
    legacy_meta = db.fetchone("SELECT value FROM app_meta WHERE key = 'sources_seeded'")
    existing_rows = db.fetchall("SELECT source_type, target FROM sources")
    existing_keys = {_source_key(str(r["source_type"]), str(r["target"])) for r in existing_rows}

    if seeded_meta is not None:
        known_keys = set(json.loads(seeded_meta["value"]))
    elif legacy_meta is not None or existing_keys:
        # Upgrade path for databases initialized before seeded_source_keys existed.
        known_keys = set(existing_keys)
    else:
        known_keys = set()

    pending = [
        entry
        for entry in entries
        if _source_key(entry["source_type"], entry["target"]) not in known_keys
    ]
    if not pending and seeded_meta is not None:
        return 0

    now = utc_now_iso()
    inserted = 0
    for entry in pending:
        key = _source_key(entry["source_type"], entry["target"])
        known_keys.add(key)
        if key in existing_keys:
            continue
        db.execute(
            """
            INSERT OR IGNORE INTO sources (name, source_type, target, area_hint, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry["name"],
                entry["source_type"],
                entry["target"],
                entry.get("area_hint", ""),
                1 if entry.get("enabled", True) else 0,
                now,
            ),
        )
        inserted += 1

    all_known = sorted(known_keys | {_source_key(e["source_type"], e["target"]) for e in entries})
    db.execute(
        "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('seeded_source_keys', ?)",
        (json.dumps(all_known),),
    )
    db.execute(
        "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('sources_seeded', '1')"
    )
    return inserted


def create_database(settings: Settings, initialize: bool = True) -> Database:
    """Instantiate either Turso (if configured) or local SQLite database."""
    db: Database
    if settings.use_turso:
        db = TursoHttpDatabase(settings.turso_database_url, settings.turso_auth_token)
    else:
        db = SqliteDatabase(settings.database_path)
    if initialize:
        init_schema(db)
        seed_default_sources(db, settings.sources_file)
    return db
