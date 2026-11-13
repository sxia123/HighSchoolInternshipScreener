"""Remotive public API adapter (keyless, respects single-call limits and attribution)."""

from __future__ import annotations

import httpx

from app.http_client import build_http_client
from app.sources.base import RawJobPosting


def fetch_remotive(
    search_query: str = "intern",
    source_name: str = "Remotive",
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Fetch remote internship listings from Remotive's public API with required source attribution."""
    url = "https://remotive.com/api/remote-jobs"
    http = client or build_http_client()
    try:
        resp = http.get(url, params={"search": search_query or "intern", "limit": 50})
        resp.raise_for_status()
        data = resp.json()
    finally:
        if client is None:
            http.close()

    postings: list[RawJobPosting] = []
    for job in data.get("jobs", []):
        job_url = str(job.get("url") or "").strip()
        title = str(job.get("title") or "").strip()
        if not job_url or not title:
            continue
        postings.append(
            RawJobPosting(
                external_id=str(job.get("id") or job_url),
                title=title,
                company=str(job.get("company_name") or "Unknown Company").strip(),
                location=str(job.get("candidate_required_location") or "Remote").strip(),
                apply_url=job_url,
                source_url=job_url,
                source_type="remotive",
                source_label=source_name,
                description=str(job.get("description") or ""),
                posted_at=str(job.get("publication_date") or ""),
                work_mode_hint="remote",
            )
        )
    return postings
