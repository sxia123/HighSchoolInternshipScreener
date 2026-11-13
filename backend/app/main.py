"""FastAPI application for the High School Internship Screener."""

from __future__ import annotations

import ipaddress
import json
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote_plus, urlparse

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.db import Database, create_database, utc_now_iso
from app.email_parser import parse_linkedin_alert_email
from app.geocoder import (
    extract_us_state_code,
    geocode_location,
    haversine_miles,
    is_nationwide_location,
    location_matches_state,
)
from app.ingest import run_scan, upsert_postings

VALID_SOURCE_TYPES = {
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "remotive",
    "rss",
    "standoutsearch",
    "pathwaystoscience",
    "github_markdown",
    "nichable",
    "studentresearchnyc",
}
URL_SOURCE_TYPES = {
    "rss",
    "standoutsearch",
    "pathwaystoscience",
    "github_markdown",
    "nichable",
    "studentresearchnyc",
}


class SourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_type: str
    target: str = Field(min_length=1, max_length=500)
    area_hint: str = Field(default="", max_length=120)
    enabled: bool = True


class SourceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    area_hint: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None


class ScanRequest(BaseModel):
    source_ids: list[int] | None = None


class EmailIngestRequest(BaseModel):
    raw_email: str = Field(min_length=10)
    default_area: str = ""


def _validate_rss_url(url: str) -> str:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="RSS target must be a valid http(s) URL.")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "0.0.0.0"} or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="Localhost RSS URLs are not permitted.")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Private IP RSS URLs are not permitted.")
    except ValueError:
        pass
    return cleaned


def _validate_source_target(source_type: str, target: str) -> str:
    if source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source_type '{source_type}'. Choose from: {sorted(VALID_SOURCE_TYPES)}",
        )
    cleaned = target.strip()
    if source_type in URL_SOURCE_TYPES:
        return _validate_rss_url(cleaned)
    return cleaned


def _build_linkedin_helper_queries(area: str) -> dict[str, Any]:
    area_clean = area.strip()
    area_clause = f' "{area_clean}"' if area_clean else ""
    queries = [
        {
            "label": "High School Internships (Broad)",
            "query": f'site:linkedin.com/jobs ("high school" OR "grades 9-12" OR "teen" OR "youth") intern{area_clause}',
        },
        {
            "label": "Summer Student / Pre-College Programs",
            "query": f'site:linkedin.com/jobs ("high school student" OR "rising senior" OR "ages 16" OR "work permit") (intern OR internship OR apprentice){area_clause}',
        },
    ]
    for item in queries:
        item["google_alerts_url"] = (
            "https://www.google.com/alerts#1:0:"
            + quote_plus(item["query"])
        )
    return {
        "area": area_clean,
        "instructions": [
            "Open Google Alerts (https://www.google.com/alerts) while signed into a Google account.",
            "Paste one of the LinkedIn search queries below.",
            "Click 'Show options', set Deliver to -> 'RSS feed', and click 'Create Alert'.",
            "Copy the generated RSS link icon URL and add it below as an RSS source.",
        ],
        "queries": queries,
    }


def create_app(
    settings: Settings | None = None,
    db_override: Database | None = None,
    allow_geocode_network: bool = True,
) -> FastAPI:
    """Build the FastAPI application with configurable settings and database."""
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if db_override is not None:
            app.state.db = db_override
            yield
        else:
            db = create_database(cfg, initialize=True)
            app.state.db = db
            try:
                yield
            finally:
                db.close()

    app = FastAPI(
        title="High School Internship Screener API",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins) or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_db() -> Database:
        return app.state.db

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        db = get_db()
        rows = db.fetchall(
            """
            SELECT eligibility_status, COUNT(*) AS cnt
            FROM internships
            WHERE is_active = 1
            GROUP BY eligibility_status
            """
        )
        counts = {"eligible": 0, "possible": 0, "rejected": 0}
        for row in rows:
            status = row["eligibility_status"]
            if status in counts:
                counts[status] = int(row["cnt"])
        counts["total"] = sum(counts.values())

        last_scan = db.fetchone(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1"
        )
        return {
            "status": "ok",
            "database_backend": db.backend_name,
            "counts": counts,
            "last_scan": last_scan,
        }

    @app.get("/api/internships")
    def list_internships(
        status: str = Query("eligible_or_possible"),
        area: str = Query(""),
        radius_miles: float = Query(50.0, ge=0.0, le=5000.0),
        include_remote: bool = Query(True),
        q: str = Query(""),
        compensation: str = Query("all"),
        work_mode: str = Query("all"),
        source_type: str = Query("all"),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        db = get_db()
        clauses = ["is_active = 1"]
        params: list[Any] = []

        if status == "eligible_or_possible":
            clauses.append("eligibility_status IN ('eligible', 'possible')")
        elif status in ("eligible", "possible", "rejected"):
            clauses.append("eligibility_status = ?")
            params.append(status)

        if compensation == "paid_or_stipend":
            clauses.append("compensation IN ('paid', 'stipend')")
        elif compensation in ("paid", "stipend", "unpaid", "unspecified"):
            clauses.append("compensation = ?")
            params.append(compensation)

        if work_mode in ("remote", "hybrid", "in-person", "unspecified"):
            clauses.append("work_mode = ?")
            params.append(work_mode)

        if source_type and source_type != "all":
            clauses.append("source_type = ?")
            params.append(source_type)

        if q.strip():
            like_term = f"%{q.strip().lower()}%"
            clauses.append(
                "(lower(title) LIKE ? OR lower(company) LIKE ? OR lower(location) LIKE ? "
                "OR lower(evidence_quote) LIKE ? OR lower(description_text) LIKE ?)"
            )
            params.extend([like_term] * 5)

        where_sql = " AND ".join(clauses)
        rows = db.fetchall(
            f"""
            SELECT id, external_id, title, company, location, latitude, longitude,
                   work_mode, apply_url, source_url, source_type, source_label,
                   posted_at, deadline, eligibility_status, eligibility_score,
                   evidence_quote, rejection_reason, grade_or_age, compensation,
                   first_seen_at, last_seen_at,
                   substr(description_text, 1, 500) AS description_preview
            FROM internships
            WHERE {where_sql}
            ORDER BY
                CASE eligibility_status
                    WHEN 'eligible' THEN 0
                    WHEN 'possible' THEN 1
                    ELSE 2
                END,
                eligibility_score DESC,
                last_seen_at DESC
            """,
            params,
        )

        area_clean = area.strip()
        area_resolved: dict[str, Any] | None = None
        filtered_rows: list[dict[str, Any]] = []

        if area_clean:
            coords = geocode_location(db, area_clean, allow_network=allow_geocode_network)
            area_city_token = area_clean.split(",")[0].strip().lower()
            if coords is not None:
                area_lat, area_lon, display_name = coords
                area_state_code = extract_us_state_code(display_name) or extract_us_state_code(area_clean)
                area_resolved = {
                    "query": area_clean,
                    "display_name": display_name,
                    "latitude": area_lat,
                    "longitude": area_lon,
                }
                for row in rows:
                    item = dict(row)
                    loc_str = item.get("location") or ""
                    is_remote_row = item.get("work_mode") == "remote"
                    is_nationwide = is_nationwide_location(loc_str)
                    dist: float | None = None
                    if item.get("latitude") is not None and item.get("longitude") is not None:
                        dist = round(
                            haversine_miles(
                                area_lat,
                                area_lon,
                                float(item["latitude"]),
                                float(item["longitude"]),
                            ),
                            1,
                        )
                    item["distance_miles"] = dist
                    city_match = bool(
                        area_city_token
                        and not area_city_token.isdigit()
                        and area_city_token in loc_str.lower()
                    )
                    state_match = bool(
                        area_state_code and location_matches_state(loc_str, area_state_code)
                    )
                    item["_geo_rank"] = (
                        0
                        if (city_match or (dist is not None and dist <= radius_miles))
                        else (1 if state_match else 2)
                    )

                    if radius_miles <= 0:
                        filtered_rows.append(item)
                    elif dist is not None and dist <= radius_miles:
                        filtered_rows.append(item)
                    elif city_match or state_match:
                        filtered_rows.append(item)
                    elif include_remote and (is_remote_row or is_nationwide):
                        filtered_rows.append(item)
            else:
                for row in rows:
                    item = dict(row)
                    item["distance_miles"] = None
                    loc_lower = (item.get("location") or "").lower()
                    if area_city_token in loc_lower or (
                        include_remote
                        and (item.get("work_mode") == "remote" or is_nationwide_location(loc_lower))
                    ):
                        filtered_rows.append(item)
        else:
            for row in rows:
                item = dict(row)
                item["distance_miles"] = None
                filtered_rows.append(item)

        if area_resolved is not None:
            filtered_rows.sort(
                key=lambda r: (
                    0 if r["eligibility_status"] == "eligible" else (1 if r["eligibility_status"] == "possible" else 2),
                    r.get("_geo_rank", 2),
                    r["distance_miles"] if r["distance_miles"] is not None else 99999.0,
                    -int(r["eligibility_score"]),
                )
            )
            for item in filtered_rows:
                item.pop("_geo_rank", None)

        total = len(filtered_rows)
        paged = filtered_rows[offset : offset + limit]
        return {
            "area_resolved": area_resolved,
            "total": total,
            "items": paged,
        }

    @app.get("/api/sources")
    def list_sources() -> list[dict[str, Any]]:
        db = get_db()
        return db.fetchall("SELECT * FROM sources ORDER BY id ASC")

    @app.post("/api/sources", status_code=201)
    def add_source(body: SourceCreateRequest) -> dict[str, Any]:
        db = get_db()
        clean_target = _validate_source_target(body.source_type, body.target)
        existing = db.fetchone(
            "SELECT id FROM sources WHERE source_type = ? AND target = ?",
            (body.source_type, clean_target),
        )
        if existing:
            raise HTTPException(status_code=409, detail="This source already exists.")

        now = utc_now_iso()
        res = db.execute(
            """
            INSERT INTO sources (name, source_type, target, area_hint, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                body.name.strip(),
                body.source_type,
                clean_target,
                body.area_hint.strip(),
                1 if body.enabled else 0,
                now,
            ),
        )
        row = db.fetchone("SELECT * FROM sources WHERE id = ?", (res.lastrowid,))
        return row or {}

    @app.patch("/api/sources/{source_id}")
    def update_source(source_id: int, body: SourceUpdateRequest) -> dict[str, Any]:
        db = get_db()
        existing = db.fetchone("SELECT * FROM sources WHERE id = ?", (source_id,))
        if not existing:
            raise HTTPException(status_code=404, detail="Source not found.")

        new_name = body.name.strip() if body.name is not None else existing["name"]
        new_area = body.area_hint.strip() if body.area_hint is not None else existing["area_hint"]
        new_enabled = (1 if body.enabled else 0) if body.enabled is not None else existing["enabled"]

        db.execute(
            "UPDATE sources SET name = ?, area_hint = ?, enabled = ? WHERE id = ?",
            (new_name, new_area, new_enabled, source_id),
        )
        return db.fetchone("SELECT * FROM sources WHERE id = ?", (source_id,)) or {}

    @app.delete("/api/sources/{source_id}", status_code=204)
    def delete_source(source_id: int) -> None:
        db = get_db()
        existing = db.fetchone("SELECT id FROM sources WHERE id = ?", (source_id,))
        if not existing:
            raise HTTPException(status_code=404, detail="Source not found.")
        db.execute("DELETE FROM sources WHERE id = ?", (source_id,))

    @app.post("/api/scan")
    def trigger_scan(
        body: ScanRequest | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if cfg.scan_trigger_secret:
            expected = f"Bearer {cfg.scan_trigger_secret}"
            if authorization != expected:
                raise HTTPException(status_code=401, detail="Invalid or missing scan authorization token.")
        db = get_db()
        source_ids = body.source_ids if body else None
        return run_scan(
            db,
            trigger="api",
            source_ids=source_ids,
            allow_geocode_network=allow_geocode_network,
        )

    @app.post("/api/ingest/email")
    async def ingest_email_json(body: EmailIngestRequest) -> dict[str, Any]:
        db = get_db()
        postings = parse_linkedin_alert_email(body.raw_email, default_area=body.default_area)
        stats = upsert_postings(
            db,
            postings,
            allow_geocode_network=allow_geocode_network,
        )
        return {
            "parsed_count": len(postings),
            **stats,
            "titles": [p.title for p in postings[:10]],
        }

    @app.post("/api/ingest/email-file")
    async def ingest_email_file(
        file: UploadFile = File(...),
        default_area: str = Form(""),
    ) -> dict[str, Any]:
        db = get_db()
        content = (await file.read()).decode("utf-8", errors="replace")
        postings = parse_linkedin_alert_email(content, default_area=default_area)
        stats = upsert_postings(
            db,
            postings,
            allow_geocode_network=allow_geocode_network,
        )
        return {
            "filename": file.filename,
            "parsed_count": len(postings),
            **stats,
            "titles": [p.title for p in postings[:10]],
        }

    @app.get("/api/scans")
    def list_scan_runs(limit: int = Query(10, ge=1, le=50)) -> list[dict[str, Any]]:
        db = get_db()
        rows = db.fetchall("SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (limit,))
        for row in rows:
            try:
                row["errors"] = json.loads(row.get("errors_json") or "[]")
            except json.JSONDecodeError:
                row["errors"] = []
        return rows

    @app.get("/api/linkedin-helper")
    def linkedin_helper(area: str = Query("")) -> dict[str, Any]:
        return _build_linkedin_helper_queries(area)

    return app


app = create_app()
