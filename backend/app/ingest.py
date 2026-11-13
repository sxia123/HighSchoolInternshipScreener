"""Ingestion, deduplication, screening, geocoding, and scan runner orchestration."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from app.db import Database, utc_now_iso
from app.geocoder import geocode_location
from app.http_client import build_http_client
from app.screener import screen_posting
from app.sources.ats import fetch_ashby, fetch_greenhouse, fetch_lever, fetch_smartrecruiters
from app.sources.base import RawJobPosting
from app.sources.github_markdown import fetch_github_markdown
from app.sources.nichable import fetch_nichable
from app.sources.pathwaystoscience import fetch_pathwaystoscience
from app.sources.remotive import fetch_remotive
from app.sources.rss import fetch_rss
from app.sources.standoutsearch import fetch_standoutsearch
from app.sources.studentresearchnyc import fetch_studentresearchnyc

TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "trk",
    "trackingid",
    "refid",
    "gh_src",
    "source",
}


def canonicalize_url(url: str) -> str:
    """Normalize a job URL by removing common tracking parameters."""
    parsed = urlparse(url.strip())
    kept_params = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in TRACKING_QUERY_PARAMS
    ]
    clean_query = urlencode(kept_params)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", clean_query, ""))


def make_dedup_key(posting: RawJobPosting) -> str:
    """Create a deterministic deduplication key across repeated scans."""
    norm_url = canonicalize_url(posting.apply_url) if posting.apply_url else ""
    if norm_url:
        raw = f"url:{norm_url}"
    else:
        norm_parts = [
            re.sub(r"\W+", "", posting.company.lower()),
            re.sub(r"\W+", "", posting.title.lower()),
            re.sub(r"\W+", "", posting.location.lower()),
        ]
        raw = "meta:" + "|".join(norm_parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def upsert_postings(
    db: Database,
    postings: list[RawJobPosting],
    allow_geocode_network: bool = True,
    max_network_geocodes: int = 15,
) -> dict[str, int]:
    """Screen, geocode, and upsert normalized postings into SQLite/Turso."""
    now = utc_now_iso()
    net_geocodes = 0
    counts = {
        "fetched": len(postings),
        "upserted": 0,
        "eligible": 0,
        "possible": 0,
        "rejected": 0,
    }

    for posting in postings:
        result = screen_posting(
            title=posting.title,
            description=posting.description,
            location=posting.location,
            work_mode_hint=posting.work_mode_hint,
            source_type=posting.source_type,
        )
        counts[result.eligibility_status] += 1

        coords: tuple[float, float, str] | None = None
        if posting.location:
            coords = geocode_location(db, posting.location, allow_network=False)
            if (
                coords is None
                and allow_geocode_network
                and result.eligibility_status != "rejected"
                and net_geocodes < max_network_geocodes
            ):
                coords = geocode_location(db, posting.location, allow_network=True)
                net_geocodes += 1

        lat = coords[0] if coords else None
        lon = coords[1] if coords else None
        dedup_key = make_dedup_key(posting)

        db.execute(
            """
            INSERT INTO internships (
                dedup_key, external_id, title, company, location, latitude, longitude,
                work_mode, apply_url, source_url, source_type, source_label,
                description_text, posted_at, deadline,
                eligibility_status, eligibility_score, evidence_quote, rejection_reason,
                grade_or_age, compensation, first_seen_at, last_seen_at, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(dedup_key) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                latitude = COALESCE(excluded.latitude, internships.latitude),
                longitude = COALESCE(excluded.longitude, internships.longitude),
                work_mode = excluded.work_mode,
                apply_url = excluded.apply_url,
                source_url = excluded.source_url,
                source_label = excluded.source_label,
                description_text = CASE
                    WHEN length(excluded.description_text) > length(internships.description_text)
                    THEN excluded.description_text
                    ELSE internships.description_text
                END,
                posted_at = COALESCE(NULLIF(excluded.posted_at, ''), internships.posted_at),
                deadline = COALESCE(NULLIF(excluded.deadline, ''), internships.deadline),
                eligibility_status = excluded.eligibility_status,
                eligibility_score = excluded.eligibility_score,
                evidence_quote = excluded.evidence_quote,
                rejection_reason = excluded.rejection_reason,
                grade_or_age = excluded.grade_or_age,
                compensation = excluded.compensation,
                last_seen_at = excluded.last_seen_at,
                is_active = 1
            """,
            (
                dedup_key,
                posting.external_id,
                posting.title,
                posting.company,
                posting.location,
                lat,
                lon,
                result.work_mode,
                posting.apply_url,
                posting.source_url or posting.apply_url,
                posting.source_type,
                posting.source_label,
                result.clean_text[:8000],
                posting.posted_at or None,
                posting.deadline or None,
                result.eligibility_status,
                result.eligibility_score,
                result.evidence_quote,
                result.rejection_reason,
                result.grade_or_age,
                result.compensation,
                now,
                now,
            ),
        )
        counts["upserted"] += 1

    return counts


def fetch_source(source: dict[str, Any], client: httpx.Client | None = None) -> list[RawJobPosting]:
    """Dispatch a source record from the sources table to its matching adapter."""
    stype = source["source_type"]
    target = source["target"]
    name = source["name"]
    area_hint = source.get("area_hint") or ""

    if stype == "greenhouse":
        return fetch_greenhouse(target, source_name=name, client=client)
    if stype == "lever":
        return fetch_lever(target, source_name=name, client=client)
    if stype == "ashby":
        return fetch_ashby(target, source_name=name, client=client)
    if stype == "smartrecruiters":
        return fetch_smartrecruiters(target, source_name=name, client=client)
    if stype == "remotive":
        return fetch_remotive(search_query=target, source_name=name, client=client)
    if stype == "rss":
        return fetch_rss(feed_url=target, source_name=name, area_hint=area_hint, client=client)
    if stype == "standoutsearch":
        return fetch_standoutsearch(target_url=target, source_name=name, client=client)
    if stype == "pathwaystoscience":
        return fetch_pathwaystoscience(list_url=target, source_name=name, client=client)
    if stype == "github_markdown":
        return fetch_github_markdown(raw_url=target, source_name=name, client=client)
    if stype == "nichable":
        return fetch_nichable(target_url=target, source_name=name, area_hint=area_hint, client=client)
    if stype == "studentresearchnyc":
        return fetch_studentresearchnyc(programs_url=target, source_name=name, area_hint=area_hint, client=client)
    raise ValueError(f"Unsupported source_type: {stype}")


def run_scan(
    db: Database,
    trigger: str = "cli",
    source_ids: list[int] | None = None,
    allow_geocode_network: bool = True,
) -> dict[str, Any]:
    """Scan all enabled sources (or specific IDs), screen results, and persist telemetry."""
    started_at = utc_now_iso()
    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        sources = db.fetchall(
            f"SELECT * FROM sources WHERE id IN ({placeholders}) ORDER BY id",
            source_ids,
        )
    else:
        sources = db.fetchall("SELECT * FROM sources WHERE enabled = 1 ORDER BY id")

    totals = {
        "sources_scanned": 0,
        "fetched": 0,
        "upserted": 0,
        "eligible": 0,
        "possible": 0,
        "rejected": 0,
    }
    errors: list[dict[str, str]] = []

    with build_http_client(timeout=15.0) as client:
        for src in sources:
            totals["sources_scanned"] += 1
            scanned_at = utc_now_iso()
            try:
                postings = fetch_source(src, client=client)
                stats = upsert_postings(
                    db,
                    postings,
                    allow_geocode_network=allow_geocode_network,
                )
                for key in ("fetched", "upserted", "eligible", "possible", "rejected"):
                    totals[key] += stats[key]
                db.execute(
                    "UPDATE sources SET last_scanned_at = ?, last_error = '' WHERE id = ?",
                    (scanned_at, src["id"]),
                )
            except Exception as exc:
                err_msg = str(exc)[:400]
                errors.append({"source": src["name"], "error": err_msg})
                db.execute(
                    "UPDATE sources SET last_scanned_at = ?, last_error = ? WHERE id = ?",
                    (scanned_at, err_msg, src["id"]),
                )

    finished_at = utc_now_iso()
    db.execute(
        """
        INSERT INTO scan_runs (
            started_at, finished_at, trigger, sources_scanned,
            fetched_count, upserted_count, eligible_count, possible_count, rejected_count, errors_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            started_at,
            finished_at,
            trigger,
            totals["sources_scanned"],
            totals["fetched"],
            totals["upserted"],
            totals["eligible"],
            totals["possible"],
            totals["rejected"],
            json.dumps(errors),
        ),
    )

    return {
        "started_at": started_at,
        "finished_at": finished_at,
        "trigger": trigger,
        **totals,
        "errors": errors,
    }
