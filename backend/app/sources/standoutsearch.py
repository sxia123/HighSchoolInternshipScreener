"""StandOutSearch public high school directory adapter (zero API keys, respects robots.txt)."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.http_client import build_http_client
from app.sources.base import RawJobPosting

DEFAULT_STANDOUT_URL = "https://www.standoutsearch.com/"


def _extract_deadline(card: BeautifulSoup) -> str:
    dl = card.select_one("span.deadline[data-deadline]")
    if not dl:
        return ""
    raw = dl.get("data-deadline", "")
    try:
        parsed = json.loads(raw)
        dates = parsed.get("dates") or []
        if dates and isinstance(dates[0], dict):
            return str(dates[0].get("date") or dates[0].get("display") or "")
    except (ValueError, TypeError):
        pass
    text = dl.get_text(" ", strip=True)
    return re.sub(r"^Deadline:\s*", "", text, flags=re.IGNORECASE).strip()


def parse_standoutsearch_html(
    html_text: str,
    source_name: str = "StandOutSearch High School Directory",
    base_url: str = DEFAULT_STANDOUT_URL,
) -> list[RawJobPosting]:
    """Parse StandOutSearch public homepage HTML cards into normalized RawJobPosting objects."""
    soup = BeautifulSoup(html_text, "html.parser")
    postings: list[RawJobPosting] = []
    seen_urls: set[str] = set()

    for card in soup.select("div.body"):
        link = card.select_one("h3.title a.title-link[href]")
        if not link:
            continue
        href = str(link["href"]).strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = link.get_text(" ", strip=True)
        org_el = card.select_one("p.org")
        company = org_el.get_text(" ", strip=True) if org_el else "StandOutSearch Partner"
        blurb_el = card.select_one("p.blurb")
        blurb = blurb_el.get_text(" ", strip=True) if blurb_el else ""

        place_el = card.select_one("span.place [data-place]") or card.select_one("span.place")
        location = ""
        if place_el:
            location = str(place_el.get("data-place") or place_el.get_text(" ", strip=True)).strip()

        deadline = _extract_deadline(card)
        work_hint = "remote" if location.lower() == "remote" else ""
        desc = f"{blurb}\nLocation: {location}." if blurb else f"{title} at {company}."
        if deadline:
            desc += f"\nApplication Deadline: {deadline}."

        postings.append(
            RawJobPosting(
                external_id=href.rstrip("/").split("/")[-1],
                title=title,
                company=company,
                location=location,
                apply_url=full_url,
                source_url=full_url,
                source_type="standoutsearch",
                source_label=source_name,
                description=desc,
                deadline=deadline,
                work_mode_hint=work_hint,
            )
        )

    return postings


def fetch_standoutsearch(
    target_url: str = DEFAULT_STANDOUT_URL,
    source_name: str = "StandOutSearch High School Directory",
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Fetch and parse high school opportunities from StandOutSearch's public page."""
    url = target_url.strip() or DEFAULT_STANDOUT_URL
    http = client or build_http_client()
    try:
        resp = http.get(url)
        resp.raise_for_status()
        return parse_standoutsearch_html(resp.text, source_name=source_name, base_url=url)
    finally:
        if client is None:
            http.close()
