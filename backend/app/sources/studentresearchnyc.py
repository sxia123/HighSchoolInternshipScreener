"""NY Science Research Mentoring Consortium (SRMC) single-page directory adapter."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.http_client import build_http_client
from app.sources.base import RawJobPosting

DEFAULT_SRMC_URL = "https://www.studentresearchnyc.org/programs/"

BOROUGH_MAP = {
    "manhattan": "Manhattan, NY",
    "bronx": "Bronx, NY",
    "brooklyn": "Brooklyn, NY",
    "queens": "Queens, NY",
    "staten island": "Staten Island, NY",
    "bayside": "Bayside, NY",
    "palisades": "Palisades, NY",
}


def _normalize_venue_and_location(venue_raw: str, area_hint: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", venue_raw).strip()
    if not cleaned:
        return ("NYC SRMC Partner", area_hint or "New York, NY")

    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    company = parts[0] if parts else cleaned

    lower = cleaned.lower()
    for token, normalized in BOROUGH_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", lower):
            return (company, normalized)

    for idx in range(1, len(parts)):
        seg = parts[idx]
        if re.fullmatch(r"NY(?:\s+\d{5})?", seg, re.IGNORECASE):
            prev = parts[idx - 1]
            if re.search(r"\d|\b(?:floor|pier|suite|st\.?|ave\.?|blvd)\b|^ny$", prev, re.IGNORECASE):
                return (company, "New York, NY")
            return (company, f"{prev}, NY")

    return (company, area_hint or "New York, NY")


def _find_card_box(anchor: Tag) -> Tag:
    box: Tag = anchor
    for _ in range(4):
        parent = box.parent
        if not isinstance(parent, Tag) or len(parent.get_text(" ", strip=True)) >= 500:
            break
        program_hrefs = {
            str(a.get("href") or "").strip()
            for a in parent.find_all("a", href=re.compile(r"/our_programs/"))
        }
        if len(program_hrefs) > 1:
            break
        box = parent
    return box


def parse_srmc_programs_html(
    html_text: str,
    source_name: str = "NY STEM Research Consortium (SRMC)",
    base_url: str = DEFAULT_SRMC_URL,
    area_hint: str = "New York, NY",
) -> list[RawJobPosting]:
    """Parse SRMC /programs/ listing in one HTTP request (respects Crawl-delay: 10)."""
    soup = BeautifulSoup(html_text, "html.parser")
    postings: list[RawJobPosting] = []
    seen_urls: set[str] = set()

    for link in soup.find_all("a", href=re.compile(r"/our_programs/")):
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        box = _find_card_box(link)
        segments = [
            re.sub(r"\s+", " ", s).strip()
            for s in box.get_text(" | ", strip=True).split(" | ")
            if s.strip()
        ]
        if not segments:
            continue

        title = segments[0]
        venue = segments[1] if len(segments) > 1 else ""
        company, location = _normalize_venue_and_location(venue, area_hint)

        description = (
            f"{title} hosted at {venue or company}. "
            "Part of the Science Research Mentoring Consortium (SRMC), connecting New York high school "
            "students with free mentored STEM research internships and academic-year/summer lab fellowships. "
            f"Location: {location}."
        )

        postings.append(
            RawJobPosting(
                external_id=href.rstrip("/").split("/")[-1],
                title=title,
                company=company,
                location=location,
                apply_url=full_url,
                source_url=base_url,
                source_type="studentresearchnyc",
                source_label=source_name,
                description=description,
                work_mode_hint="in-person",
            )
        )

    return postings


def fetch_studentresearchnyc(
    programs_url: str = DEFAULT_SRMC_URL,
    source_name: str = "NY STEM Research Consortium (SRMC)",
    area_hint: str = "New York, NY",
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Fetch SRMC mentored high school STEM research programs from a single page."""
    url = programs_url.strip() or DEFAULT_SRMC_URL
    http = client or build_http_client()
    try:
        resp = http.get(url)
        resp.raise_for_status()
        return parse_srmc_programs_html(
            resp.text,
            source_name=source_name,
            base_url=url,
            area_hint=area_hint,
        )
    finally:
        if client is None:
            http.close()
