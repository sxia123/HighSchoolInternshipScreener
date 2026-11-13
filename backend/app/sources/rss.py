"""RSS 2.0 & Atom feed adapter (supports Google Alerts RSS feeds for LinkedIn)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

import httpx

from app.http_client import build_http_client
from app.screener import strip_html
from app.sources.base import RawJobPosting


def unwrap_google_alert_url(url: str) -> str:
    """Extract the underlying target URL from Google Alerts redirect links."""
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        qs = parse_qs(parsed.query)
        for key in ("url", "q"):
            if key in qs and qs[key]:
                return qs[key][0].strip()
    return cleaned


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _child_text(elem: ET.Element, *names: str) -> str:
    for child in elem:
        if _local_name(child.tag) in names:
            if child.text and child.text.strip():
                return child.text.strip()
            # Handle Atom <link href="..."/>
            href = child.attrib.get("href", "").strip()
            if href:
                return href
    return ""


def _infer_company_and_title(
    raw_title: str,
    url: str,
    source_name: str = "",
) -> tuple[str, str]:
    """Parse common LinkedIn/Google Alert/RSS title formats like 'Role - Company'."""
    title = strip_html(raw_title)
    title = re.sub(r"\s*\|\s*LinkedIn\s*$", "", title, flags=re.IGNORECASE).strip()
    if " hiring " in title:
        # Pattern: "Company hiring High School Intern in Austin, TX"
        parts = title.split(" hiring ", 1)
        company = parts[0].strip()
        role = parts[1].strip()
        role = re.sub(r"\s+in\s+[^|]+$", "", role).strip()
        return (role or title, company)
    if " - " in title:
        parts = [p.strip() for p in title.rsplit(" - ", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            if "linkedin.com" in url.lower() or len(parts[1]) <= 40:
                return (parts[0], parts[1])
    return (title, source_name or "Via RSS Feed")


def _extract_location_hint(raw_title: str, description: str, area_hint: str) -> str:
    m = re.search(r"\bin\s+([A-Z][a-zA-Z\s.]+,\s*[A-Z]{2})\b", strip_html(raw_title))
    if m:
        return m.group(1).strip()
    m_desc = re.search(r"\b([A-Z][a-zA-Z\s.]+,\s*[A-Z]{2})\b", strip_html(description))
    if m_desc:
        return m_desc.group(1).strip()
    return area_hint


def parse_feed_xml(
    xml_text: str,
    source_name: str,
    area_hint: str = "",
) -> list[RawJobPosting]:
    """Parse an RSS 2.0 or Atom XML string into normalized RawJobPosting objects."""
    root = ET.fromstring(xml_text)
    root_name = _local_name(root.tag).lower()

    entries: list[ET.Element] = []
    if root_name == "feed":
        entries = [el for el in root if _local_name(el.tag) == "entry"]
    else:
        for child in root:
            if _local_name(child.tag) == "channel":
                entries.extend(el for el in child if _local_name(el.tag) == "item")

    postings: list[RawJobPosting] = []
    for entry in entries:
        raw_title = _child_text(entry, "title")
        raw_link = _child_text(entry, "link")
        if not raw_link:
            raw_link = _child_text(entry, "id", "guid")
        target_url = unwrap_google_alert_url(raw_link)
        if not raw_title or not target_url.startswith(("http://", "https://")):
            continue

        desc = _child_text(entry, "content", "description", "summary")
        published = _child_text(entry, "published", "updated", "pubDate")
        title, company = _infer_company_and_title(raw_title, target_url, source_name=source_name)
        location = _extract_location_hint(raw_title, desc, area_hint)
        label = (
            f"{source_name} (LinkedIn)"
            if "linkedin.com" in target_url.lower() and "linkedin" not in source_name.lower()
            else source_name
        )

        postings.append(
            RawJobPosting(
                external_id=target_url,
                title=title,
                company=company,
                location=location,
                apply_url=target_url,
                source_url=target_url,
                source_type="rss",
                source_label=label,
                description=desc,
                posted_at=published,
            )
        )
    return postings


def fetch_rss(
    feed_url: str,
    source_name: str,
    area_hint: str = "",
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Download and parse an RSS/Atom feed URL."""
    http = client or build_http_client()
    try:
        resp = http.get(feed_url)
        resp.raise_for_status()
        return parse_feed_xml(resp.text, source_name=source_name, area_hint=area_hint)
    finally:
        if client is None:
            http.close()
