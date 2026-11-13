"""Public unauthenticated ATS board adapters (Greenhouse, Lever, Ashby, SmartRecruiters)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.geocoder import NON_GEO_RE
from app.http_client import build_http_client
from app.sources.base import RawJobPosting, looks_like_student_candidate


def _format_slug_company(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title()


def _epoch_ms_to_iso(raw_ms: Any) -> str:
    if not raw_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(float(raw_ms) / 1000.0, tz=timezone.utc)
        return dt.replace(microsecond=0).isoformat()
    except (ValueError, TypeError, OverflowError):
        return ""


def fetch_greenhouse(
    slug: str,
    source_name: str,
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Fetch public jobs from Greenhouse Job Board API (no API key required)."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    http = client or build_http_client()
    try:
        resp = http.get(url, params={"content": "true"})
        resp.raise_for_status()
        data = resp.json()
    finally:
        if client is None:
            http.close()

    postings: list[RawJobPosting] = []
    for job in data.get("jobs", []):
        title = str(job.get("title") or "").strip()
        desc = str(job.get("content") or "")
        if not title or not looks_like_student_candidate(title, desc):
            continue
        loc_obj = job.get("location") or {}
        location = str(loc_obj.get("name") or "").strip() if isinstance(loc_obj, dict) else ""
        work_mode_hint = location if NON_GEO_RE.match(location) else ""
        if (not location or NON_GEO_RE.match(location)) and isinstance(job.get("offices"), list):
            office_names = [
                str(o.get("name") or "").strip()
                for o in job["offices"]
                if isinstance(o, dict) and o.get("name")
            ]
            if office_names:
                location = " • ".join(office_names)
        company = str(job.get("company_name") or _format_slug_company(slug)).strip()
        apply_url = str(job.get("absolute_url") or "").strip()
        if not apply_url:
            continue
        postings.append(
            RawJobPosting(
                external_id=str(job.get("id") or apply_url),
                title=title,
                company=company,
                location=location,
                apply_url=apply_url,
                source_url=apply_url,
                source_type="greenhouse",
                source_label=source_name,
                description=desc,
                posted_at=str(job.get("first_published") or job.get("updated_at") or ""),
                deadline=str(job.get("application_deadline") or ""),
                work_mode_hint=work_mode_hint,
            )
        )
    return postings


def fetch_lever(
    slug: str,
    source_name: str,
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Fetch public postings from Lever API (no API key required)."""
    url = f"https://api.lever.co/v0/postings/{slug}"
    http = client or build_http_client()
    try:
        resp = http.get(url, params={"mode": "json"})
        resp.raise_for_status()
        items = resp.json()
    finally:
        if client is None:
            http.close()

    if not isinstance(items, list):
        return []

    company = _format_slug_company(slug)
    postings: list[RawJobPosting] = []
    for item in items:
        title = str(item.get("text") or "").strip()
        desc_parts = [
            str(item.get("descriptionPlain") or item.get("description") or ""),
            str(item.get("descriptionBodyPlain") or item.get("descriptionBody") or ""),
            str(item.get("additionalPlain") or item.get("additional") or ""),
        ]
        for lst in item.get("lists") or []:
            if isinstance(lst, dict):
                desc_parts.append(f"{lst.get('text', '')}: {lst.get('content', '')}")
        desc = "\n".join(p for p in desc_parts if p)

        if not title or not looks_like_student_candidate(title, desc):
            continue

        categories = item.get("categories") or {}
        location = str(categories.get("location") or "").strip()
        workplace = str(item.get("workplaceType") or "").strip()
        apply_url = str(item.get("hostedUrl") or item.get("applyUrl") or "").strip()
        if not apply_url:
            continue

        postings.append(
            RawJobPosting(
                external_id=str(item.get("id") or apply_url),
                title=title,
                company=company,
                location=location,
                apply_url=apply_url,
                source_url=apply_url,
                source_type="lever",
                source_label=source_name,
                description=desc,
                posted_at=_epoch_ms_to_iso(item.get("createdAt")),
                work_mode_hint=workplace,
            )
        )
    return postings


def fetch_ashby(
    slug: str,
    source_name: str,
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Fetch public job postings from Ashby Job Board API (no API key required)."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    http = client or build_http_client()
    try:
        resp = http.get(url)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if client is None:
            http.close()

    company = _format_slug_company(slug)
    postings: list[RawJobPosting] = []
    for job in data.get("jobs", []):
        title = str(job.get("title") or "").strip()
        desc = str(job.get("descriptionPlain") or job.get("descriptionHtml") or "")
        if not title or not looks_like_student_candidate(title, desc):
            continue

        location = str(job.get("location") or "").strip()
        workplace = str(job.get("workplaceType") or "")
        if not workplace and job.get("isRemote"):
            workplace = "remote"
        apply_url = str(job.get("jobUrl") or job.get("applyUrl") or "").strip()
        if not apply_url:
            continue

        postings.append(
            RawJobPosting(
                external_id=str(job.get("id") or apply_url),
                title=title,
                company=company,
                location=location,
                apply_url=apply_url,
                source_url=apply_url,
                source_type="ashby",
                source_label=source_name,
                description=desc,
                posted_at=str(job.get("publishedAt") or ""),
                work_mode_hint=workplace,
            )
        )
    return postings


def fetch_smartrecruiters(
    slug: str,
    source_name: str,
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Fetch internship postings from SmartRecruiters public API (no API key required)."""
    base_url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    http = client or build_http_client()
    try:
        resp = http.get(base_url, params={"limit": 100})
        resp.raise_for_status()
        items = resp.json().get("content", [])

        postings: list[RawJobPosting] = []
        for item in items:
            title = str(item.get("name") or "").strip()
            if not title or not looks_like_student_candidate(title):
                continue
            posting_id = str(item.get("id") or "").strip()
            if not posting_id:
                continue

            detail_resp = http.get(f"{base_url}/{posting_id}")
            detail = detail_resp.json() if detail_resp.status_code == 200 else {}
            sections = (detail.get("jobAd") or {}).get("sections") or {}
            desc_parts = []
            for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
                sec = sections.get(key)
                if isinstance(sec, dict) and sec.get("text"):
                    desc_parts.append(str(sec["text"]))

            loc = item.get("location") or {}
            loc_parts = [loc.get("city"), loc.get("region"), loc.get("country")]
            location = ", ".join(str(p) for p in loc_parts if p)
            company_obj = item.get("company") or {}
            company = str(company_obj.get("name") or _format_slug_company(slug)).strip()
            apply_url = str(detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{slug}/{posting_id}")

            postings.append(
                RawJobPosting(
                    external_id=posting_id,
                    title=title,
                    company=company,
                    location=location,
                    apply_url=apply_url,
                    source_url=apply_url,
                    source_type="smartrecruiters",
                    source_label=source_name,
                    description="\n".join(desc_parts),
                    posted_at=str(item.get("releasedDate") or ""),
                    work_mode_hint="remote" if loc.get("remote") else "",
                )
            )
        return postings
    finally:
        if client is None:
            http.close()
