"""Normalized posting data model and shared filtering helpers for source adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass

CANDIDATE_TITLE_RE = re.compile(
    r"\b(intern|internship|internships|interns|apprentice|apprenticeship|externship|high\s+school|youth|teen|pre-?college|student)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RawJobPosting:
    external_id: str
    title: str
    company: str
    location: str
    apply_url: str
    source_type: str
    source_label: str
    description: str = ""
    source_url: str = ""
    posted_at: str = ""
    deadline: str = ""
    work_mode_hint: str = ""


def looks_like_student_candidate(title: str, description: str = "") -> bool:
    """Fast pre-check so large company ATS feeds skip unrelated full-time senior roles."""
    if CANDIDATE_TITLE_RE.search(title):
        return True
    if description and re.search(
        r"\b(high\s+school\s+(?:student|intern|internship)|youth\s+internship|teen\s+internship)\b",
        description,
        re.IGNORECASE,
    ):
        return True
    return False
