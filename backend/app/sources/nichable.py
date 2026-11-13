"""Nichable public high school opportunities directory adapter (respects robots.txt)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.http_client import build_http_client
from app.sources.base import RawJobPosting

DEFAULT_NICHABLE_URL = "https://nichable.app/opportunities?category=internship"

SKIP_CATEGORIES = {"scholarship", "competition"}
KNOWN_CATEGORIES = {
    "internship",
    "research",
    "job",
    "program",
    "volunteer",
    "scholarship",
    "competition",
}
PAY_LABELS = {"paid", "paid to you", "free", "unpaid"}
DETAIL_SKIP_LABELS = KNOWN_CATEGORIES | PAY_LABELS | {
    "deadline",
    "status",
    "grade levels",
    "eligibility",
    "location",
    "cost",
    "about",
    "who can apply",
    "key details",
    "sign up",
    "log in to save",
    "copy link",
    "share",
    "more from this org",
    "rolling",
    "open",
    "opening soon",
    "closed",
    "hybrid",
    "remote",
    "in-person",
    "add deadline to calendar",
}

LOCAL_REGION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "albany": (
        "albany",
        "rensselaer",
        "schenectady",
        "troy",
        "saratoga-springs",
        "saratoga-county",
        "latham",
        "misci",
        "cherry-hill",
        "st-peter",
        "ellis",
        "ualbany",
        "wadsworth",
    ),
}

CITY_STATE_RE = re.compile(r"^[A-Za-z0-9 .'-]+,\s*[A-Z]{2}$")
DEADLINE_HINT_RE = re.compile(r"\b(?:due|deadline|opening\s+soon|rolling)\b", re.IGNORECASE)


def _is_allowed_nichable_path(path: str) -> bool:
    """Enforce robots.txt Disallow paths even when scanning user-configured URLs."""
    disallowed = (
        "/dashboard",
        "/saved",
        "/settings",
        "/search",
        "/compare",
        "/build-list",
        "/applications",
        "/help",
        "/notifications",
        "/onboarding",
        "/api",
    )
    lower = path.lower()
    return not any(lower == p or lower.startswith(p + "/") for p in disallowed)


def _find_card_container(anchor: Tag) -> Tag:
    node: Tag | None = anchor
    for _ in range(6):
        if node is None:
            break
        classes = " ".join(node.get("class") or [])
        if "rounded" in classes:
            return node
        node = node.parent if isinstance(node.parent, Tag) else None
    return anchor.parent if isinstance(anchor.parent, Tag) else anchor


def _normalize_location(raw: str, area_hint: str = "") -> str:
    loc = re.sub(r"\s*\([^)]+\)\s*$", "", raw.strip()).strip()
    if not loc:
        return area_hint
    if loc.lower() in ("nationwide", "united states", "us"):
        return "Across the US"
    return loc


def parse_nichable_cards(
    html_text: str,
    source_name: str = "Nichable High School Opportunities",
    base_url: str = DEFAULT_NICHABLE_URL,
    area_hint: str = "",
) -> list[RawJobPosting]:
    """Parse Nichable listing page HTML cards into normalized RawJobPosting objects."""
    soup = BeautifulSoup(html_text, "html.parser")
    postings: list[RawJobPosting] = []
    seen_urls: set[str] = set()

    for link in soup.find_all("a", href=re.compile(r"^/opportunities/")):
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        title = str(link.get("title") or link.get_text(" ", strip=True)).strip()
        if not title:
            continue

        container = _find_card_container(link)
        parts = [
            p.strip()
            for chunk in container.get_text(" | ", strip=True).split(" | ")
            for p in chunk.split("·")
            if p.strip()
        ]

        # Expected header layout: <h3><a ...>title</a></h3><span>company</span>
        company = "Nichable Partner"
        heading = link.find_parent(["h2", "h3"])
        if heading:
            sibling_span = heading.find_next_sibling("span")
            if sibling_span and sibling_span.get_text(strip=True):
                company = sibling_span.get_text(" ", strip=True)

        category = ""
        pay_tag = ""
        location = ""
        deadline = ""

        for part in parts:
            lower = part.lower()
            if part == title or part == company:
                continue
            if lower in KNOWN_CATEGORIES and not category:
                category = part
            elif lower in PAY_LABELS and not pay_tag:
                pay_tag = part
            elif (
                CITY_STATE_RE.match(part)
                or lower in ("nationwide", "remote", "online", "virtual", "multiple locations")
            ) and not location:
                location = _normalize_location(part)
            elif DEADLINE_HINT_RE.search(part):
                cleaned_dl = re.sub(r"^deadline$", "", part, flags=re.IGNORECASE).strip()
                if cleaned_dl:
                    deadline = cleaned_dl
            elif parts and part != company and re.match(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", part):
                deadline = part

        if category.lower() in SKIP_CATEGORIES:
            continue

        loc_final = location or area_hint
        work_hint = "remote" if loc_final.lower() in ("remote", "online", "virtual") else ""
        desc_parts = [f"{title} at {company}."]
        if category:
            desc_parts.append(f"Category: {category}.")
        desc_parts.append("Target Audience: High school students.")
        if pay_tag:
            desc_parts.append(f"Compensation: {pay_tag}.")
        if loc_final:
            desc_parts.append(f"Location: {loc_final}.")
        if deadline:
            desc_parts.append(f"Application Deadline: {deadline}.")

        postings.append(
            RawJobPosting(
                external_id=href.rstrip("/").split("/")[-1],
                title=title,
                company=company,
                location=loc_final,
                apply_url=full_url,
                source_url=full_url,
                source_type="nichable",
                source_label=source_name,
                description=" ".join(desc_parts),
                deadline=deadline,
                work_mode_hint=work_hint,
            )
        )

    return postings


def _extract_labeled_fields(soup: BeautifulSoup) -> dict[str, str]:
    """Extract key-value detail fields rendered on a Nichable /opportunities/<slug> page."""
    main = soup.find("main") or soup.body or soup
    tokens = [t.strip() for t in main.get_text("\n", strip=True).split("\n") if t.strip()]
    fields: dict[str, str] = {}
    keys = {
        "deadline": "deadline",
        "status": "status",
        "grade levels": "grades",
        "eligibility": "eligibility",
        "location": "location",
        "cost": "cost",
        "about": "about",
        "who can apply": "who_can_apply",
    }
    for idx, tok in enumerate(tokens[:-1]):
        mapped = keys.get(tok.lower())
        if mapped and mapped not in fields:
            val = tokens[idx + 1]
            if val not in ("·", "/") and val.lower() not in keys:
                fields[mapped] = val
    return fields


def parse_nichable_detail(
    html_text: str,
    url: str,
    source_name: str = "Nichable High School Opportunities",
    area_hint: str = "",
) -> RawJobPosting | None:
    """Parse a Nichable /opportunities/<slug> detail page into a RawJobPosting."""
    soup = BeautifulSoup(html_text, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title:
        return None

    fields = _extract_labeled_fields(soup)
    main = soup.find("main") or soup.body or soup
    header_text = main.get_text(" | ", strip=True)[:500]
    lower_head = header_text.lower()
    if any(f"| {cat} |" in lower_head for cat in SKIP_CATEGORIES):
        return None

    company = "Nichable Partner"
    org_link = soup.find("a", href=re.compile(r"^/orgs?/"))
    if org_link and org_link.get_text(strip=True):
        company = org_link.get_text(" ", strip=True)
    elif h1:
        for el in h1.find_all_next(["a", "span", "p"], limit=8):
            txt = el.get_text(" ", strip=True)
            if txt and txt not in ("·", title) and len(txt) < 120:
                if txt.lower() not in DETAIL_SKIP_LABELS:
                    company = txt
                    break

    location = _normalize_location(fields.get("location", ""), area_hint)
    grades = fields.get("grades") or fields.get("eligibility") or "High school students"
    cost = fields.get("cost", "")
    deadline = fields.get("deadline", "")
    about = fields.get("about", "")
    who = fields.get("who_can_apply", "")

    desc_parts = []
    if about:
        desc_parts.append(about)
    else:
        desc_parts.append(f"{title} at {company}.")
    if who:
        desc_parts.append(f"Who can apply: {who}.")
    desc_parts.append(f"Eligibility: {grades}.")
    if cost:
        desc_parts.append(f"Compensation: {cost}.")
    if location:
        desc_parts.append(f"Location: {location}.")
    if deadline and "rolling" not in deadline.lower():
        desc_parts.append(f"Application Deadline: {deadline}.")

    work_hint = ""
    if "remote" in lower_head or location.lower() in ("remote", "online", "virtual"):
        work_hint = "remote"
    elif "hybrid" in lower_head:
        work_hint = "hybrid"

    return RawJobPosting(
        external_id=url.rstrip("/").split("/")[-1],
        title=title,
        company=company,
        location=location,
        apply_url=url,
        source_url=url,
        source_type="nichable",
        source_label=source_name,
        description=" ".join(desc_parts),
        deadline=deadline,
        work_mode_hint=work_hint,
    )


def _with_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    qs["page"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _discover_local_sitemap_urls(
    client: httpx.Client,
    local_url: str,
    existing_urls: set[str],
    max_details: int = 12,
) -> list[str]:
    parsed = urlparse(local_url)
    slug = parsed.path.rstrip("/").split("/")[-1].lower()
    if not slug:
        return []
    keywords = LOCAL_REGION_KEYWORDS.get(slug, (slug, slug.replace("-", " ")))
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    resp = client.get(sitemap_url)
    resp.raise_for_status()

    matches: list[str] = []
    for loc in re.findall(r"<loc>(https?://[^<]+)</loc>", resp.text):
        if "/opportunities/" not in loc or loc in existing_urls:
            continue
        opp_slug = loc.rsplit("/", 1)[-1].lower()
        if any(kw in opp_slug for kw in keywords):
            matches.append(loc)
            if len(matches) >= max_details:
                break
    return matches


def fetch_nichable(
    target_url: str = DEFAULT_NICHABLE_URL,
    source_name: str = "Nichable High School Opportunities",
    area_hint: str = "",
    client: httpx.Client | None = None,
    max_pages: int = 8,
) -> list[RawJobPosting]:
    """Fetch public Nichable high school listings cleanly within robots.txt rules."""
    url = target_url.strip() or DEFAULT_NICHABLE_URL
    parsed = urlparse(url)
    if not _is_allowed_nichable_path(parsed.path):
        raise ValueError(f"Nichable path {parsed.path!r} is disallowed by robots.txt")

    http = client or build_http_client()
    try:
        all_postings: list[RawJobPosting] = []
        seen_urls: set[str] = set()

        resp = http.get(url)
        resp.raise_for_status()
        first_batch = parse_nichable_cards(
            resp.text,
            source_name=source_name,
            base_url=url,
            area_hint=area_hint,
        )
        for item in first_batch:
            seen_urls.add(item.apply_url)
            all_postings.append(item)

        # Follow pagination cleanly on /opportunities pages.
        if parsed.path.startswith("/opportunities"):
            for page_num in range(2, max_pages + 1):
                if f"page={page_num}" not in resp.text:
                    break
                page_url = _with_page(url, page_num)
                page_resp = http.get(page_url)
                page_resp.raise_for_status()
                batch = parse_nichable_cards(
                    page_resp.text,
                    source_name=source_name,
                    base_url=url,
                    area_hint=area_hint,
                )
                if not batch:
                    break
                for item in batch:
                    if item.apply_url not in seen_urls:
                        seen_urls.add(item.apply_url)
                        all_postings.append(item)
                resp = page_resp

        # For /local/<city> hubs, enrich listing cards and seasonal sitemap entries.
        if parsed.path.startswith("/local/"):
            enriched: list[RawJobPosting] = []
            # Enrich local listing cards first (only non-skipped opportunities) for richer grade/cost/about info.
            for idx, item in enumerate(all_postings):
                if idx < 8:
                    try:
                        d_resp = http.get(item.apply_url)
                        if d_resp.status_code == 200:
                            detailed = parse_nichable_detail(
                                d_resp.text,
                                item.apply_url,
                                source_name=source_name,
                                area_hint=item.location or area_hint,
                            )
                            if detailed is not None:
                                enriched.append(detailed)
                                continue
                    except httpx.HTTPError:
                        pass
                enriched.append(item)
            all_postings = enriched

            try:
                m_hint_state = re.search(r",\s*([A-Z]{2})\b", area_hint)
                hint_state = m_hint_state.group(1) if m_hint_state else ""
                extra_urls = _discover_local_sitemap_urls(http, url, seen_urls, max_details=12)
                for extra_url in extra_urls:
                    d_resp = http.get(extra_url)
                    if d_resp.status_code != 200:
                        continue
                    detailed = parse_nichable_detail(
                        d_resp.text,
                        extra_url,
                        source_name=source_name,
                        area_hint=area_hint,
                    )
                    if detailed is None:
                        continue
                    m_loc_state = re.search(r",\s*([A-Z]{2})\b", detailed.location)
                    if hint_state and m_loc_state and m_loc_state.group(1) != hint_state:
                        continue
                    seen_urls.add(extra_url)
                    all_postings.append(detailed)
            except httpx.HTTPError:
                pass

        return all_postings
    finally:
        if client is None:
            http.close()
