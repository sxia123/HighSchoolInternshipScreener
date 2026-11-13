"""Tests for SQLite and Turso Hrana HTTP database adapters."""

import json
from pathlib import Path

import httpx
import pytest

from app.db import (
    SqliteDatabase,
    TursoHttpDatabase,
    decode_hrana_cell,
    encode_hrana_arg,
    init_schema,
    normalize_turso_http_url,
    seed_default_sources,
)


def test_sqlite_schema_and_single_seed(tmp_path: Path):
    db_file = tmp_path / "test.db"
    sources_json = tmp_path / "sources.json"
    sources_json.write_text(
        json.dumps([{"name": "Test Board", "source_type": "greenhouse", "target": "acme"}]),
        encoding="utf-8",
    )

    db = SqliteDatabase(db_file)
    try:
        init_schema(db)
        assert seed_default_sources(db, sources_json) == 1
        assert len(db.fetchall("SELECT * FROM sources")) == 1

        # Deleting seeded source prevents re-seeding on next init.
        db.execute("DELETE FROM sources")
        assert seed_default_sources(db, sources_json) == 0

        # Adding a newly shipped source later seeds only the new entry.
        sources_json.write_text(
            json.dumps(
                [
                    {"name": "Test Board", "source_type": "greenhouse", "target": "acme"},
                    {"name": "StandOutSearch", "source_type": "standoutsearch", "target": "default"},
                ]
            ),
            encoding="utf-8",
        )
        assert seed_default_sources(db, sources_json) == 1
        rows = db.fetchall("SELECT * FROM sources")
        assert len(rows) == 1
        assert rows[0]["source_type"] == "standoutsearch"
    finally:
        db.close()


def test_hrana_arg_and_cell_round_trip():
    assert encode_hrana_arg(None) == {"type": "null"}
    assert encode_hrana_arg(True) == {"type": "integer", "value": "1"}
    assert encode_hrana_arg(42) == {"type": "integer", "value": "42"}
    assert encode_hrana_arg(37.77) == {"type": "float", "value": 37.77}
    assert encode_hrana_arg("Austin") == {"type": "text", "value": "Austin"}

    assert decode_hrana_cell({"type": "null"}) is None
    assert decode_hrana_cell({"type": "integer", "value": "42"}) == 42
    assert decode_hrana_cell({"type": "float", "value": 37.77}) == 37.77
    assert decode_hrana_cell({"type": "text", "value": "Austin"}) == "Austin"


def test_turso_url_normalization():
    assert (
        normalize_turso_http_url("libsql://my-db-org.turso.io")
        == "https://my-db-org.turso.io/v2/pipeline"
    )
    assert (
        normalize_turso_http_url("https://my-db-org.turso.io/v2/pipeline")
        == "https://my-db-org.turso.io/v2/pipeline"
    )


def test_turso_http_pipeline_execution_and_errors():
    captured_payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_payloads.append(body)
        sql = body["requests"][0]["stmt"]["sql"]
        if "BAD_SQL" in sql:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"type": "error", "error": {"message": "syntax error"}},
                        {"type": "ok", "response": {"type": "close"}},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "type": "ok",
                        "response": {
                            "type": "execute",
                            "result": {
                                "cols": [{"name": "id"}, {"name": "title"}, {"name": "score"}],
                                "rows": [
                                    [
                                        {"type": "integer", "value": "7"},
                                        {"type": "text", "value": "HS Intern"},
                                        {"type": "float", "value": 95.5},
                                    ]
                                ],
                                "affected_row_count": 0,
                                "last_insert_rowid": None,
                            },
                        },
                    },
                    {"type": "ok", "response": {"type": "close"}},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    db = TursoHttpDatabase("libsql://demo.turso.io", "secret-token", client=client)
    rows = db.fetchall("SELECT id, title, score FROM internships WHERE id = ?", (7,))
    assert rows == [{"id": 7, "title": "HS Intern", "score": 95.5}]
    assert captured_payloads[0]["requests"][0]["stmt"]["args"] == [
        {"type": "integer", "value": "7"}
    ]

    with pytest.raises(RuntimeError, match="syntax error"):
        db.execute("BAD_SQL")
    client.close()
