"""Pathways to Science (NSF/IBP) high school STEM directory adapter."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.http_client import build_http_client
from app.sources.base import RawJobPosting

DEFAULT_PTS_URL = (
    "https://www.pathwaystoscience.org/programs.aspx?u=HighSchool_High%20School%20Students&submit=y"
)
PTS_BASE_URL = "https://www.pathwaystoscience.org/"


def parse_pathwaystoscience_list(html_text: str) -> list[dict[str, str]]:
    """Extract unique program entries from the Pathways to Science search results page."""
    soup = BeautifulSoup(html_text, "html.parser")
    seen_hrefs: set[str] = set()
    entries: list[dict[str, str]] = []

    for card in soup.select("div.progigert"):
        link = card.find("a", href=lambda h: bool(h and "programhub.aspx" in h.lower()))
        if not link:
            continue
        href = str(link["href"]).strip()
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        title = link.get_text(" ", strip=True)
        snippet_div = card.find("div")
        snippet = snippet_div.get_text(" ", strip=True) if snippet_div else ""
        snippet = re.sub(r"\s*\.\.\.read more\s*$", "", snippet, flags=re.IGNORECASE).strip()

        entries.append(
            {
                "title": title,
                "detail_path": href,
                "detail_url": urljoin(PTS_BASE_URL, href.lstrip("/")),
                "snippet": snippet,
            }
        )
    return entries


def parse_pathwaystoscience_detail(
    html_text: str,
    detail_url: str,
    fallback_title: str = "",
) -> dict[str, str]:
    """Extract external apply URL, host institution, description, and nationwide status."""
    soup = BeautifulSoup(html_text, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]

    # Find official external link ("Click Here to Learn More and Apply!" or "Program Website").
    apply_url = detail_url
    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True).lower()
        href = str(anchor["href"]).strip()
        if href.startswith(("http://", "https://")) and "pathwaystoscience.org" not in href.lower():
            if any(k in label for k in ("learn more and apply", "program website", "apply")):
                apply_url = href
                break

    # Extract Participating Institution(s) from institution links.
    institutions = [
        a.get_text(" ", strip=True)
        for a in soup.find_all("a", href=True)
        if "institution.aspx" in a["href"].lower() and a.get_text(" ", strip=True)
    ]
    company = institutions[0] if institutions else "Pathways to Science Host"

    # Extract Description block between "Description:" and "Participating Institution(s)" / "For more information".
    desc_lines: list[str] = []
    capture = False
    for line in lines:
        lower = line.lower()
        if lower == "description:":
            capture = True
            continue
        if capture and (
            lower.startswith("participating institution")
            or lower.startswith("program materials")
            or lower.startswith("this program can be described")
        ):
            break
        if capture:
            desc_lines.append(line)

    is_nationwide = bool(
        soup.find("img", src=lambda s: bool(s and "nationwide" in s.lower()))
        or soup.find("img", alt=lambda a: bool(a and "nationwide" in a.lower()))
    )
    location = "Across the US" if is_nationwide else "United States"

    description = " ".join(desc_lines).strip()
    if description:
        description = f"Academic Level: High School Students.\n{description}"
    else:
        description = f"Academic Level: High School Students. {fallback_title}"

    return {
        "apply_url": apply_url,
        "company": company,
        "location": location,
        "description": description,
    }


def fetch_pathwaystoscience(
    list_url: str = DEFAULT_PTS_URL,
    source_name: str = "Pathways to Science (High School STEM)",
    client: httpx.Client | None = None,
    fetch_details: bool = True,
    max_details: int = 100,
) -> list[RawJobPosting]:
    """Fetch high school STEM programs from Pathways to Science."""
    url = list_url.strip() or DEFAULT_PTS_URL
    http = client or build_http_client(timeout=15.0)
    try:
        resp = http.get(url)
        resp.raise_for_status()
        entries = parse_pathwaystoscience_list(resp.text)

        postings: list[RawJobPosting] = []
        for idx, entry in enumerate(entries):
            apply_url = entry["detail_url"]
            company = "Pathways to Science"
            location = "United States"
            desc = f"Academic Level: High School Students. {entry['snippet']}"

            if fetch_details and idx < max_details:
                try:
                    d_resp = http.get(entry["detail_url"])
                    if d_resp.status_code == 200:
                        parsed = parse_pathwaystoscience_detail(
                            d_resp.text,
                            detail_url=entry["detail_url"],
                            fallback_title=entry["title"],
                        )
                        apply_url = parsed["apply_url"]
                        company = parsed["company"]
                        location = parsed["location"]
                        desc = parsed["description"]
                except Exception:
                    pass

            postings.append(
                RawJobPosting(
                    external_id=entry["detail_path"],
                    title=entry["title"],
                    company=company,
                    location=location,
                    apply_url=apply_url,
                    source_url=entry["detail_url"],
                    source_type="pathwaystoscience",
                    source_label=source_name,
                    description=desc,
                )
            )
        return postings
    finally:
        if client is None:
            http.close()
