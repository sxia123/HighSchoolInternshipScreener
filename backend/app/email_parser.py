"""Parse LinkedIn Job Alert emails (.eml, HTML, or plain text) into normalized postings."""

from __future__ import annotations

import email
import re
from email import policy
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.sources.base import RawJobPosting

LINKEDIN_JOB_URL_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?linkedin\.com/(?:comm/)?jobs/view/(\d+)[^\s\"'<>]*",
    re.IGNORECASE,
)

GENERIC_ANCHOR_TEXTS = {
    "",
    "view job",
    "apply",
    "apply now",
    "see job",
    "see more jobs",
    "view all jobs",
    "manage job alerts",
    "unsubscribe",
    "learn more",
}


def canonicalize_linkedin_job_url(url: str) -> str:
    """Strip LinkedIn tracking query params and /comm prefix into a stable job URL."""
    match = LINKEDIN_JOB_URL_RE.search(url)
    if match:
        job_id = match.group(1)
        return f"https://www.linkedin.com/jobs/view/{job_id}/"
    parsed = urlparse(url.strip())
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _extract_email_bodies(raw_content: str) -> tuple[str, str]:
    """Return (html_body, text_body) from either RFC822 .eml text or raw HTML/plain text."""
    stripped = raw_content.lstrip()
    looks_like_rfc822 = bool(
        re.match(r"^(?:Return-Path|Delivered-To|Received|From|Subject|MIME-Version):", stripped, re.IGNORECASE)
    )
    if looks_like_rfc822:
        msg = email.message_from_string(raw_content, policy=policy.default)
        html_parts: list[str] = []
        text_parts: list[str] = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/html":
                    html_parts.append(part.get_content())
                elif ctype == "text/plain":
                    text_parts.append(part.get_content())
        else:
            ctype = msg.get_content_type()
            payload = msg.get_content()
            if ctype == "text/html":
                html_parts.append(payload)
            else:
                text_parts.append(payload)
        return ("\n".join(html_parts), "\n".join(text_parts))

    if "<html" in stripped.lower() or "<a " in stripped.lower():
        return (raw_content, "")
    return ("", raw_content)


def _split_company_location(lines: list[str], title: str, default_area: str) -> tuple[str, str, str]:
    filtered = [line.strip() for line in lines if line.strip() and line.strip() != title]
    company = filtered[0] if filtered else "LinkedIn Employer"
    location = filtered[1] if len(filtered) > 1 else default_area
    # Handle "Acme Corp · Austin, TX" single-line formatting.
    if " · " in company and len(filtered) == 1:
        c_part, _, loc_part = company.partition(" · ")
        company = c_part.strip()
        location = loc_part.strip()
    snippet = " ".join(filtered[2:5]) if len(filtered) > 2 else " ".join(filtered)
    return (company, location, snippet)


def _parse_html_alerts(html_body: str, default_area: str) -> list[RawJobPosting]:
    soup = BeautifulSoup(html_body, "html.parser")
    by_url: dict[str, RawJobPosting] = {}

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        match = LINKEDIN_JOB_URL_RE.search(href)
        if not match:
            continue
        job_id = match.group(1)
        canonical_url = canonicalize_linkedin_job_url(href)
        anchor_text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if anchor_text.lower() in GENERIC_ANCHOR_TEXTS or len(anchor_text) < 3:
            continue

        container = anchor.find_parent(["td", "div", "li", "article", "section"]) or anchor.parent
        raw_lines = (
            [ln.strip() for ln in container.get_text("\n").splitlines() if ln.strip()]
            if container is not None
            else [anchor_text]
        )
        company, location, snippet = _split_company_location(raw_lines, anchor_text, default_area)

        if canonical_url not in by_url:
            by_url[canonical_url] = RawJobPosting(
                external_id=job_id,
                title=anchor_text,
                company=company,
                location=location,
                apply_url=canonical_url,
                source_url=canonical_url,
                source_type="linkedin_email",
                source_label="LinkedIn Job Alert",
                description=snippet or f"{anchor_text} at {company} ({location})",
            )
    return list(by_url.values())


def _parse_text_alerts(text_body: str, default_area: str) -> list[RawJobPosting]:
    lines = [ln.strip() for ln in text_body.splitlines()]
    by_url: dict[str, RawJobPosting] = {}

    for idx, line in enumerate(lines):
        for match in LINKEDIN_JOB_URL_RE.finditer(line):
            job_id = match.group(1)
            canonical_url = canonicalize_linkedin_job_url(match.group(0))
            if canonical_url in by_url:
                continue

            context_before = [ln for ln in lines[max(0, idx - 4) : idx] if ln and "http" not in ln.lower()]
            title = context_before[-3] if len(context_before) >= 3 else (
                context_before[-2] if len(context_before) >= 2 else (
                    context_before[-1] if context_before else f"LinkedIn Job #{job_id}"
                )
            )
            remaining = context_before[-2:] if len(context_before) >= 3 else context_before[-1:]
            company, location, snippet = _split_company_location(remaining, title, default_area)

            by_url[canonical_url] = RawJobPosting(
                external_id=job_id,
                title=title,
                company=company,
                location=location,
                apply_url=canonical_url,
                source_url=canonical_url,
                source_type="linkedin_email",
                source_label="LinkedIn Job Alert",
                description=snippet or f"{title} at {company} ({location})",
            )
    return list(by_url.values())


def parse_linkedin_alert_email(
    raw_content: str,
    default_area: str = "",
) -> list[RawJobPosting]:
    """Extract LinkedIn job listings from an .eml file, HTML snippet, or plain-text alert email."""
    html_body, text_body = _extract_email_bodies(raw_content)
    if html_body:
        html_results = _parse_html_alerts(html_body, default_area=default_area)
        if html_results:
            return html_results
    if text_body:
        return _parse_text_alerts(text_body, default_area=default_area)
    return []
