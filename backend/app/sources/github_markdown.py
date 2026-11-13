"""GitHub curated Markdown table adapter for high school internship repositories."""

from __future__ import annotations

import re

import httpx

from app.http_client import build_http_client
from app.sources.base import RawJobPosting

MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
SKIP_SECTION_RE = re.compile(
    r"\b(competitions?|scholarships?|education|contributing|acknowledgements?|courses?)\b",
    re.IGNORECASE,
)


def _split_md_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return all(re.match(r"^:?-{2,}:?$", c.replace(" ", "")) for c in cells if c)


def _clean_cell_text(raw: str) -> str:
    # Replace markdown links [Label](url) with Label and strip bold markers.
    text = MD_LINK_RE.sub(r"\1", raw)
    text = text.replace("**", "").replace("`", "").replace("&#8209;", "-")
    return re.sub(r"\s+", " ", text).strip()


def _extract_first_url(cells: list[str]) -> str:
    for cell in cells:
        m = MD_LINK_RE.search(cell)
        if m:
            return m.group(2).strip()
    return ""


def _normalize_pay_token(raw_pay: str) -> str:
    cleaned = raw_pay.strip()
    if cleaned in ("$ ->", "$->", "Paid"):
        return "Paid internship."
    if cleaned in ("$ <-", "$<-", "Costs money"):
        return "Costs money / paid tuition program."
    if cleaned in ("--", "0", "Free", "Unpaid"):
        return "Free / unpaid program." if cleaned in ("0", "Free") else "Unpaid internship."
    return cleaned


def parse_github_markdown_tables(
    md_text: str,
    source_name: str = "GitHub High School List",
    repo_url: str = "",
) -> list[RawJobPosting]:
    """Parse Markdown internship tables from curated GitHub high school repositories."""
    lines = md_text.splitlines()
    postings: list[RawJobPosting] = []
    seen_urls: set[str] = set()
    current_heading = ""
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#"):
            current_heading = line.lstrip("#").strip()
            i += 1
            continue

        if SKIP_SECTION_RE.search(current_heading):
            i += 1
            continue

        if "|" in line and i + 1 < len(lines):
            header_cells = _split_md_row(line)
            sep_cells = _split_md_row(lines[i + 1])
            if len(header_cells) >= 3 and _is_separator_row(sep_cells):
                headers = [_clean_cell_text(h).lower() for h in header_cells]
                i += 2
                while i < len(lines) and "|" in lines[i]:
                    row_cells = _split_md_row(lines[i])
                    i += 1
                    if len(row_cells) < 2 or _is_separator_row(row_cells):
                        continue

                    row_map = {
                        headers[idx]: row_cells[idx]
                        for idx in range(min(len(headers), len(row_cells)))
                    }
                    apply_url = _extract_first_url(row_cells)
                    if not apply_url or apply_url in seen_urls:
                        continue
                    seen_urls.add(apply_url)

                    raw_title = (
                        row_map.get("name")
                        or row_map.get("role")
                        or row_map.get("program")
                        or row_cells[0]
                    )
                    title = _clean_cell_text(raw_title)
                    if not title:
                        continue

                    company = _clean_cell_text(
                        row_map.get("company")
                        or row_map.get("organization")
                        or row_map.get("provider")
                        or title.split(":")[0]
                    )
                    location = _clean_cell_text(row_map.get("location") or "")
                    mode = _clean_cell_text(row_map.get("mode") or row_map.get("format") or "")
                    if not location and mode.lower() in ("online", "remote", "virtual"):
                        location = "Remote"
                    grades = _clean_cell_text(
                        row_map.get("grade level") or row_map.get("eligible grades") or ""
                    )
                    pay_raw = _clean_cell_text(
                        row_map.get("paid?") or row_map.get("cost") or ""
                    )
                    deadline = _clean_cell_text(row_map.get("deadline") or row_map.get("application deadline") or "")
                    short_desc = _clean_cell_text(
                        row_map.get("short description") or row_map.get("description") or ""
                    )

                    desc_parts = [short_desc] if short_desc else []
                    desc_parts.append("Curated for high school students.")
                    if grades:
                        desc_parts.append(f"Eligible high school grades: {grades}.")
                    if pay_raw:
                        desc_parts.append(_normalize_pay_token(pay_raw))
                    if mode:
                        desc_parts.append(f"Format: {mode}.")
                    if deadline and deadline.lower() not in ("tbd", "n/a"):
                        desc_parts.append(f"Deadline: {deadline}.")

                    postings.append(
                        RawJobPosting(
                            external_id=apply_url,
                            title=title,
                            company=company,
                            location=location or "United States",
                            apply_url=apply_url,
                            source_url=repo_url or apply_url,
                            source_type="github_markdown",
                            source_label=source_name,
                            description="\n".join(desc_parts),
                            deadline=deadline,
                            work_mode_hint="remote" if mode.lower() in ("online", "remote", "virtual") else mode,
                        )
                    )
                continue
        i += 1

    return postings


def fetch_github_markdown(
    raw_url: str,
    source_name: str = "GitHub High School List",
    client: httpx.Client | None = None,
) -> list[RawJobPosting]:
    """Download a raw GitHub README.md URL and parse internship Markdown tables."""
    http = client or build_http_client()
    try:
        resp = http.get(raw_url.strip())
        resp.raise_for_status()
        return parse_github_markdown_tables(
            resp.text,
            source_name=source_name,
            repo_url=raw_url.strip(),
        )
    finally:
        if client is None:
            http.close()
