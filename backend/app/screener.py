"""Rule-based High School Internship Screener (zero API keys required)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Word-boundary internship role detectors (explicitly avoids "internal"/"international").
INTERNSHIP_TITLE_RE = re.compile(
    r"\b(intern|internship|internships|interns|apprentice|apprenticeship|externship)\b",
    re.IGNORECASE,
)
YOUTH_PROGRAM_TITLE_RE = re.compile(
    r"\b(high school|youth|teen|pre-?college|summer student)\b.{0,35}\b(program|programs|fellow|fellowship|assistant|intern|associate|worker|employment|commission|corps|guide)\b",
    re.IGNORECASE,
)
INTERNSHIP_BODY_RE = re.compile(
    r"\b(internships?|high\s+school\s+interns?|summer\s+interns?|student\s+interns?|youth\s+employment|apprenticeships?|research\s+(?:programs?|experiences?|opportunity|opportunities|internships?|academy)|mentored\s+lab\s+research|summer\s+programs?|summer\s+scholars?|fellowships?|volunteer\s+(?:programs?|positions?)|junior\s+volunteers?|high\s+school\s+(?:juniors?\s+and\s+seniors?|students?)\s+can\s+volunteer)\b",
    re.IGNORECASE,
)

# Strong positive high-school eligibility indicators.
STRONG_HS_PATTERNS: tuple[tuple[re.Pattern[str], int, str], ...] = (
    (
        re.compile(
            r"\b(?:high\s+school|secondary\s+school)\s+(?:student|students|intern|interns|internship|freshman|sophomore|junior|juniors|senior|seniors)\b|\bhigh\s+schoolers?\b|\bacademic\s+level:\s*high\s+school\b",
            re.IGNORECASE,
        ),
        50,
        "Explicitly open to high school students",
    ),
    (
        re.compile(
            r"\bcurrently\s+(?:enrolled\s+in|attending)\s+(?:a\s+)?high\s+school\b",
            re.IGNORECASE,
        ),
        50,
        "Requires current high school enrollment",
    ),
    (
        re.compile(
            r"\b(?:grades?\s*(?:9|10|11|12)\s*(?:-|–|to|through)\s*(?:10|11|12)|(?:9th|10th|11th|12th)\s+grade(?:r|rs)?)\b",
            re.IGNORECASE,
        ),
        45,
        "Specifies high school grade levels (9-12)",
    ),
    (
        re.compile(
            r"\b(?:ages?\s*1[4-7]\b(?:\s*(?:-|–|to|and)\s*1[5-9])?|must\s+be\s+(?:at\s+least\s+)?1[4-7]\s+years?\s+old)\b",
            re.IGNORECASE,
        ),
        40,
        "Targets high-school-age teens (14-17+)",
    ),
    (
        re.compile(
            r"\b(?:youth\s+(?:employment|internship|intern|apprentice)|teen\s+(?:intern|internship|program)|pre-?college|work(?:ing)?\s+permit)\b",
            re.IGNORECASE,
        ),
        35,
        "Youth / pre-college internship or work permit mentioned",
    ),
    (
        re.compile(
            r"(?<!college\s)(?<!university\s)\brising\s+(?:sophomore|junior|senior)s?\b",
            re.IGNORECASE,
        ),
        25,
        "Mentions rising student grade",
    ),
)

MODERATE_HS_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\bno\s+(?:college\s+)?degree\s+required\b", re.IGNORECASE), 15),
    (re.compile(r"\bno\s+prior\s+experience\b", re.IGNORECASE), 10),
    (re.compile(r"\bhigh\s+school\b", re.IGNORECASE), 10),
)

# Disqualifiers that mark a posting as college/grad/adult-only unless overridden by explicit HS eligibility.
COLLEGE_ONLY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:currently\s+)?(?:enrolled\s+in|pursuing(?:\s+or\s+(?:recently\s+)?completed|received)?)\s+(?:a|an)?\s*(?:accredited\s+)?(?:4-year|four-year|associate(?:'s)?|bachelor(?:'s)?|b\.?\s*s\.?|b\.?\s*a\.?|master(?:'s)?|m\.?\s*s\.?|m\.?\s*a\.?|mba|ph\.?\s*d\.?|doctorate|undergraduate|graduate|college|university)?\s*(?:degree|diploma\s+from\s+a\s+university)\b",
            re.IGNORECASE,
        ),
        "Requires college or graduate degree enrollment",
    ),
    (
        re.compile(
            r"\b(?:pursuing|enrolled\s+in|completing)\s+(?:a\s+)?(?:bachelor(?:'s)?|master(?:'s)?|ph\.?\s*d\.?|undergraduate|graduate)\b",
            re.IGNORECASE,
        ),
        "Requires college or graduate degree enrollment",
    ),
    (
        re.compile(
            r"\b(?:graduate|graduating)\s+(?:in|between)\b.{0,50}\bwith\s+a\s+(?:bachelor(?:'s)?|master(?:'s)?|ph\.?\s*d\.?|degree)\b",
            re.IGNORECASE,
        ),
        "Requires upcoming university graduation with a degree",
    ),
    (
        re.compile(
            r"\b(?:undergraduate|graduate|college|university|phd|ph\.d\.|doctoral|mba|master'?s|bachelor'?s)\s+(?:student|students|intern|internship|candidate|candidates|degree\s+program)\b",
            re.IGNORECASE,
        ),
        "Restricted to college or graduate students",
    ),
    (
        re.compile(
            r"\b(?:freshmen|sophomores|juniors|seniors)\s+in\s+(?:college|university)\b|\brising\s+(?:college|university)\s+(?:sophomore|junior|senior)\b",
            re.IGNORECASE,
        ),
        "Restricted to college undergraduates",
    ),
    (
        re.compile(
            r"\benrolled\s+full[- ]time\s+in\s+(?:an?\s+)?(?:accredited\s+)?(?:college|university)\b",
            re.IGNORECASE,
        ),
        "Requires full-time university enrollment",
    ),
)

PHD_OR_SENIOR_TITLE_RE = re.compile(
    r"\b(phd|ph\.d\.|postdoc|post-doc|mba|senior|sr\.?|staff|principal|director|vp|vice president|manager|lead)\b",
    re.IGNORECASE,
)

ADULT_DIPLOMA_TRAP_RE = re.compile(
    r"\b(?:high\s+school\s+diploma|ged|hsd)(?:\s+or\s+(?:equivalent|ged))?\s+(?:is\s+)?required\b",
    re.IGNORECASE,
)
EXPERIENCE_YEARS_RE = re.compile(
    r"\b(?:[2-9]|1\d)\+?\s+years?\s+(?:of\s+)?(?:professional|relevant|related|industry|work)?\s*experience\b",
    re.IGNORECASE,
)
TUITION_PROGRAM_RE = re.compile(
    r"\b(?:costs?\s+money|paid\s+tuition(?:\s+program)?|tuition\s+(?:is|of|required)|10-session\s+bootcamp|coding\s+bootcamp|pre-?college\s+(?:summer\s+|winter\s+)?(?:online\s+)?courses?)\b",
    re.IGNORECASE,
)

# Structured extraction helpers.
GRADE_AGE_EXTRACT_RE = re.compile(
    r"\b(?:grades?\s*(?:9|10|11|12)(?:\s*(?:-|–|to|through)\s*(?:10|11|12))?\b|(?:9th|10th|11th|12th)\s+grade(?:r|rs)?\b|ages?\s*1[4-8]\b(?:\+|(?:\s*(?:-|–|to)\s*1[5-9]\b))?|at\s+least\s+1[4-8]\s+years?\s+old\b|high\s+school\s+(?:freshman|sophomore|juniors?|seniors?)(?:\s+(?:and|or)\s+(?:juniors?|seniors?))?\b)",
    re.IGNORECASE,
)
PAID_RE = re.compile(
    r"(?:\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:/|\s*per\s*)?(?:hr|hour|wk|week|mo|month)|paid\s+internship|paid\s+to\s+you|compensation:\s*paid|hourly\s+(?:pay|rate|wage)|competitive\s+compensation)",
    re.IGNORECASE,
)
STIPEND_RE = re.compile(r"\bstipend\b", re.IGNORECASE)
UNPAID_RE = re.compile(
    r"\b(?:unpaid|volunteer|academic\s+credit\s+only|for\s+school\s+credit\s+only)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ScreeningResult:
    eligibility_status: str  # "eligible" | "possible" | "rejected"
    eligibility_score: int
    evidence_quote: str
    rejection_reason: str
    grade_or_age: str
    compensation: str  # "paid" | "stipend" | "unpaid" | "unspecified"
    work_mode: str  # "remote" | "hybrid" | "in-person" | "unspecified"
    clean_text: str


def strip_html(raw: str) -> str:
    """Convert HTML job descriptions into clean plain text while preserving sentence boundaries."""
    if not raw:
        return ""
    unescaped = html.unescape(raw)
    if "<" not in unescaped and ">" not in unescaped:
        text = re.sub(r"[ \t\r\f\v]+", " ", unescaped)
        return re.sub(r" *\n+ *", "\n", text).strip()

    soup = BeautifulSoup(unescaped, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr"]):
        block.insert_before("\n")
        block.append("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\s+([.,;!?])", r"\1", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\s*\n+\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _trim_quote(sentence: str, max_len: int = 220) -> str:
    if len(sentence) <= max_len:
        return sentence
    return sentence[: max_len - 3].rstrip() + "..."


def _find_matching_sentence(sentences: list[str], pattern: re.Pattern[str]) -> str:
    for sentence in sentences:
        if pattern.search(sentence):
            return _trim_quote(sentence)
    return ""


def detect_work_mode(title: str, location: str, text: str, hint: str = "") -> str:
    """Infer work mode ('remote', 'hybrid', 'in-person', or 'unspecified')."""
    combined_hint = f"{hint} {location} {title}".lower()
    if "hybrid" in combined_hint:
        return "hybrid"
    if "remote" in combined_hint or "work from home" in combined_hint:
        return "remote"
    if "on-site" in combined_hint or "onsite" in combined_hint or "in-person" in combined_hint:
        return "in-person"

    body_lower = text.lower()
    if re.search(r"\bhybrid\b", body_lower):
        return "hybrid"
    if re.search(r"\b(fully remote|100% remote|remote internship|work from home)\b", body_lower):
        return "remote"
    if re.search(r"\b(on-?site|in-person|in person)\b", body_lower):
        return "in-person"
    if location.strip() and not re.search(
        r"\b(anywhere|remote|across\s+the\s+us|nationwide|united\s+states)\b",
        location.lower(),
    ):
        return "in-person"
    return "unspecified"


def detect_compensation(text: str) -> str:
    """Detect whether the internship mentions paid wages, a stipend, or unpaid status."""
    if STIPEND_RE.search(text):
        return "stipend"
    if UNPAID_RE.search(text):
        return "unpaid"
    if PAID_RE.search(text):
        return "paid"
    return "unspecified"


def is_internship_role(title: str, clean_text: str, source_type: str = "") -> bool:
    """Verify the posting is actually an internship, apprenticeship, or youth student program."""
    if INTERNSHIP_TITLE_RE.search(title) or YOUTH_PROGRAM_TITLE_RE.search(title):
        return True
    if source_type in (
        "linkedin_email",
        "rss",
        "standoutsearch",
        "pathwaystoscience",
        "github_markdown",
        "nichable",
        "studentresearchnyc",
    ) and INTERNSHIP_BODY_RE.search(clean_text):
        return True
    if YOUTH_PROGRAM_TITLE_RE.search(clean_text[:500]):
        return True
    return False


def screen_posting(
    title: str,
    description: str,
    location: str = "",
    work_mode_hint: str = "",
    source_type: str = "",
) -> ScreeningResult:
    """Evaluate a job posting for high school student eligibility without LLM API keys."""
    clean_text = strip_html(description)
    combined_text = f"{title}. {clean_text}".strip()
    sentences = _split_sentences(combined_text)

    work_mode = detect_work_mode(title, location, clean_text, work_mode_hint)
    compensation = detect_compensation(combined_text)
    grade_tokens: list[str] = []
    for m in GRADE_AGE_EXTRACT_RE.finditer(combined_text):
        token = m.group(0).strip()
        if token.lower() not in {t.lower() for t in grade_tokens}:
            grade_tokens.append(token)
    grade_or_age = ", ".join(grade_tokens[:2])

    if TUITION_PROGRAM_RE.search(combined_text) and compensation not in ("paid", "stipend"):
        return ScreeningResult(
            eligibility_status="rejected",
            eligibility_score=10,
            evidence_quote=_find_matching_sentence(sentences, TUITION_PROGRAM_RE) or _trim_quote(title),
            rejection_reason="Tuition-charging bootcamp or course rather than a paid/free internship",
            grade_or_age=grade_or_age,
            compensation=compensation,
            work_mode=work_mode,
            clean_text=clean_text,
        )

    if not is_internship_role(title, clean_text, source_type):
        return ScreeningResult(
            eligibility_status="rejected",
            eligibility_score=0,
            evidence_quote=_trim_quote(sentences[0]) if sentences else title,
            rejection_reason="Not an internship, apprenticeship, or youth program",
            grade_or_age=grade_or_age,
            compensation=compensation,
            work_mode=work_mode,
            clean_text=clean_text,
        )

    # Check title-level senior/PhD indicators unless title explicitly specifies high school.
    title_has_hs = bool(re.search(r"\bhigh\s+school\b", title, re.IGNORECASE))
    if PHD_OR_SENIOR_TITLE_RE.search(title) and not title_has_hs:
        return ScreeningResult(
            eligibility_status="rejected",
            eligibility_score=5,
            evidence_quote=title,
            rejection_reason="Title indicates senior, management, MBA, or PhD-level role",
            grade_or_age=grade_or_age,
            compensation=compensation,
            work_mode=work_mode,
            clean_text=clean_text,
        )

    # Score positive high-school signals.
    score = 0
    has_explicit_hs = False
    best_positive_quote = ""

    for pattern, points, _desc in STRONG_HS_PATTERNS:
        if pattern.search(combined_text):
            score += points
            if points >= 35:
                has_explicit_hs = True
            if not best_positive_quote:
                best_positive_quote = _find_matching_sentence(sentences, pattern)

    for pattern, points in MODERATE_HS_PATTERNS:
        if pattern.search(combined_text):
            score += points
            if not best_positive_quote:
                best_positive_quote = _find_matching_sentence(sentences, pattern)

    # Check disqualifiers.
    disqualifier_reason = ""
    disqualifier_quote = ""

    for pattern, reason in COLLEGE_ONLY_PATTERNS:
        if pattern.search(combined_text):
            disqualifier_reason = reason
            disqualifier_quote = _find_matching_sentence(sentences, pattern)
            break

    if not disqualifier_reason and ADULT_DIPLOMA_TRAP_RE.search(combined_text) and not has_explicit_hs:
        disqualifier_reason = "Requires completed high school diploma/GED (adult entry role)"
        disqualifier_quote = _find_matching_sentence(sentences, ADULT_DIPLOMA_TRAP_RE)

    if not disqualifier_reason and EXPERIENCE_YEARS_RE.search(combined_text) and not has_explicit_hs:
        disqualifier_reason = "Requires 2+ years of prior work experience"
        disqualifier_quote = _find_matching_sentence(sentences, EXPERIENCE_YEARS_RE)

    # If the posting explicitly invites high schoolers (e.g. "open to high school and college students"),
    # keep it eligible unless it's a PhD/postdoc/senior title caught above.
    if has_explicit_hs:
        return ScreeningResult(
            eligibility_status="eligible",
            eligibility_score=min(100, max(score, 50)),
            evidence_quote=best_positive_quote or _trim_quote(title),
            rejection_reason="",
            grade_or_age=grade_or_age or "High School",
            compensation=compensation,
            work_mode=work_mode,
            clean_text=clean_text,
        )

    if disqualifier_reason:
        return ScreeningResult(
            eligibility_status="rejected",
            eligibility_score=max(0, min(25, score)),
            evidence_quote=disqualifier_quote or _trim_quote(title),
            rejection_reason=disqualifier_reason,
            grade_or_age=grade_or_age,
            compensation=compensation,
            work_mode=work_mode,
            clean_text=clean_text,
        )

    if score >= 30:
        return ScreeningResult(
            eligibility_status="eligible",
            eligibility_score=min(100, score),
            evidence_quote=best_positive_quote or _trim_quote(title),
            rejection_reason="",
            grade_or_age=grade_or_age,
            compensation=compensation,
            work_mode=work_mode,
            clean_text=clean_text,
        )

    # Internship with no degree restriction found, but no explicit high-school text either.
    fallback_quote = best_positive_quote or (
        _trim_quote(sentences[0]) if sentences else _trim_quote(title)
    )
    return ScreeningResult(
        eligibility_status="possible",
        eligibility_score=max(20, score + 20),
        evidence_quote=fallback_quote,
        rejection_reason="",
        grade_or_age=grade_or_age,
        compensation=compensation,
        work_mode=work_mode,
        clean_text=clean_text,
    )
