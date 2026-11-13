"""Lightweight geocoder with SQLite/Turso cache, offline US metro seeds, and Nominatim fallback."""

from __future__ import annotations

import math
import re
import time

from app.db import Database, utc_now_iso
from app.http_client import build_http_client

# Pre-seeded major US hubs so common locations work instantaneously with zero network requests.
BUILTIN_LOCATIONS: dict[str, tuple[float, float, str]] = {
    "new york, ny": (40.7128, -74.0060, "New York, NY"),
    "nyc": (40.7128, -74.0060, "New York, NY"),
    "brooklyn, ny": (40.6782, -73.9442, "Brooklyn, NY"),
    "brooklyn": (40.6782, -73.9442, "Brooklyn, NY"),
    "manhattan, ny": (40.7831, -73.9712, "Manhattan, NY"),
    "manhattan": (40.7831, -73.9712, "Manhattan, NY"),
    "bronx, ny": (40.8448, -73.8648, "Bronx, NY"),
    "bronx": (40.8448, -73.8648, "Bronx, NY"),
    "queens, ny": (40.7282, -73.7949, "Queens, NY"),
    "queens": (40.7282, -73.7949, "Queens, NY"),
    "staten island, ny": (40.5795, -74.1502, "Staten Island, NY"),
    "bayside, ny": (40.7586, -73.7654, "Bayside, NY"),
    "albany, ny": (42.6526, -73.7562, "Albany, NY"),
    "rensselaer, ny": (42.6426, -73.7429, "Rensselaer, NY"),
    "troy, ny": (42.7284, -73.6918, "Troy, NY"),
    "latham, ny": (42.7470, -73.7590, "Latham, NY"),
    "colonie, ny": (42.7179, -73.8335, "Colonie, NY"),
    "cohoes, ny": (42.7742, -73.7001, "Cohoes, NY"),
    "watervliet, ny": (42.7301, -73.7012, "Watervliet, NY"),
    "delmar, ny": (42.6220, -73.8326, "Delmar, NY"),
    "east greenbush, ny": (42.5931, -73.7023, "East Greenbush, NY"),
    "schenectady, ny": (42.8142, -73.9396, "Schenectady, NY"),
    "clifton park, ny": (42.8598, -73.7812, "Clifton Park, NY"),
    "malta, ny": (42.9765, -73.7918, "Malta, NY"),
    "saratoga springs, ny": (43.0831, -73.7846, "Saratoga Springs, NY"),
    "glens falls, ny": (43.3095, -73.6440, "Glens Falls, NY"),
    "palisades, ny": (41.0112, -73.9135, "Palisades, NY"),
    "west point, ny": (41.3915, -73.9560, "West Point, NY"),
    "stony brook, ny": (40.9257, -73.1409, "Stony Brook, NY"),
    "ithaca, ny": (42.4430, -76.5019, "Ithaca, NY"),
    "syracuse, ny": (43.0481, -76.1474, "Syracuse, NY"),
    "rochester, ny": (43.1566, -77.6088, "Rochester, NY"),
    "buffalo, ny": (42.8864, -78.8784, "Buffalo, NY"),
    "san francisco, ca": (37.7749, -122.4194, "San Francisco, CA"),
    "sf, ca": (37.7749, -122.4194, "San Francisco, CA"),
    "san jose, ca": (37.3382, -121.8863, "San Jose, CA"),
    "los angeles, ca": (34.0522, -118.2437, "Los Angeles, CA"),
    "san diego, ca": (32.7157, -117.1611, "San Diego, CA"),
    "seattle, wa": (47.6062, -122.3321, "Seattle, WA"),
    "austin, tx": (30.2672, -97.7431, "Austin, TX"),
    "dallas, tx": (32.7767, -96.7970, "Dallas, TX"),
    "houston, tx": (29.7604, -95.3698, "Houston, TX"),
    "chicago, il": (41.8781, -87.6298, "Chicago, IL"),
    "boston, ma": (42.3601, -71.0589, "Boston, MA"),
    "cambridge, ma": (42.3736, -71.1097, "Cambridge, MA"),
    "washington, dc": (38.9072, -77.0369, "Washington, DC"),
    "atlanta, ga": (33.7490, -84.3880, "Atlanta, GA"),
    "miami, fl": (25.7617, -80.1918, "Miami, FL"),
    "denver, co": (39.7392, -104.9903, "Denver, CO"),
    "phoenix, az": (33.4484, -112.0740, "Phoenix, AZ"),
    "philadelphia, pa": (39.9526, -75.1652, "Philadelphia, PA"),
    "pittsburgh, pa": (40.4406, -79.9959, "Pittsburgh, PA"),
    "minneapolis, mn": (44.9778, -93.2650, "Minneapolis, MN"),
    "portland, or": (45.5152, -122.6784, "Portland, OR"),
    "raleigh, nc": (35.7796, -78.6382, "Raleigh, NC"),
    "charlotte, nc": (35.2271, -80.8431, "Charlotte, NC"),
    "detroit, mi": (42.3314, -83.0458, "Detroit, MI"),
}

US_STATE_CENTROIDS: dict[str, tuple[float, float, str]] = {
    "alabama": (32.8067, -86.7911, "Alabama"),
    "alaska": (61.3707, -152.4044, "Alaska"),
    "arizona": (33.7298, -111.4312, "Arizona"),
    "arkansas": (34.9697, -92.3731, "Arkansas"),
    "california": (36.1162, -119.6816, "California"),
    "colorado": (39.0598, -105.3111, "Colorado"),
    "connecticut": (41.5978, -72.7554, "Connecticut"),
    "delaware": (39.3185, -75.5071, "Delaware"),
    "district of columbia": (38.9072, -77.0369, "Washington, DC"),
    "florida": (27.7663, -81.6868, "Florida"),
    "georgia": (33.0406, -83.6431, "Georgia"),
    "hawaii": (21.0943, -157.4983, "Hawaii"),
    "idaho": (44.2405, -114.4788, "Idaho"),
    "illinois": (40.3495, -88.9861, "Illinois"),
    "indiana": (39.8494, -86.2583, "Indiana"),
    "iowa": (42.0115, -93.2105, "Iowa"),
    "kansas": (38.5266, -96.7265, "Kansas"),
    "kentucky": (37.6681, -84.6701, "Kentucky"),
    "louisiana": (31.1695, -91.8678, "Louisiana"),
    "maine": (44.6939, -69.3819, "Maine"),
    "maryland": (39.0639, -76.8021, "Maryland"),
    "massachusetts": (42.2302, -71.5301, "Massachusetts"),
    "michigan": (43.3266, -84.5361, "Michigan"),
    "minnesota": (45.6945, -93.9002, "Minnesota"),
    "mississippi": (32.7416, -89.6787, "Mississippi"),
    "missouri": (38.4561, -92.2884, "Missouri"),
    "montana": (46.9219, -110.4544, "Montana"),
    "nebraska": (41.1254, -98.2681, "Nebraska"),
    "nevada": (38.3135, -117.0554, "Nevada"),
    "new hampshire": (43.4525, -71.5639, "New Hampshire"),
    "new jersey": (40.2989, -74.5210, "New Jersey"),
    "new mexico": (34.8405, -106.2485, "New Mexico"),
    "new york": (42.1657, -74.9481, "New York"),
    "north carolina": (35.6301, -79.8064, "North Carolina"),
    "north dakota": (47.5289, -99.7840, "North Dakota"),
    "ohio": (40.3888, -82.7649, "Ohio"),
    "oklahoma": (35.5653, -96.9289, "Oklahoma"),
    "oregon": (44.5720, -122.0709, "Oregon"),
    "pennsylvania": (40.5908, -77.2098, "Pennsylvania"),
    "rhode island": (41.6809, -71.5118, "Rhode Island"),
    "south carolina": (33.8569, -80.9450, "South Carolina"),
    "south dakota": (44.2998, -99.4388, "South Dakota"),
    "tennessee": (35.7478, -86.6923, "Tennessee"),
    "texas": (31.0545, -97.5635, "Texas"),
    "utah": (40.1500, -111.8624, "Utah"),
    "vermont": (44.0459, -72.7107, "Vermont"),
    "virginia": (37.7693, -78.1700, "Virginia"),
    "washington": (47.4009, -121.4905, "Washington"),
    "west virginia": (38.4912, -80.9545, "West Virginia"),
    "wisconsin": (44.2685, -89.6165, "Wisconsin"),
    "wyoming": (42.7559, -107.3025, "Wyoming"),
}

US_STATE_CODE_TO_NAME: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

NON_GEO_RE = re.compile(
    r"^\s*(?:remote|anywhere|worldwide|global|united states|usa|us|u\.s\.|across the us|nationwide(?:\s*\(us\))?|multiple(?: us)? locations|various|tbd|n/?a|in[- ]office|on[- ]?site|in[- ]person|hybrid|flexible)?\s*$",
    re.IGNORECASE,
)

NATIONWIDE_RE = re.compile(
    r"\b(?:across\s+the\s+us|nationwide|all\s+us\s+states|multiple\s+us\s+locations)\b",
    re.IGNORECASE,
)

US_ZIP_RE = re.compile(r"^(\d{5})(?:-\d{4})?$")
US_CITY_STATE_RE = re.compile(r"^([A-Za-z0-9 .'-]+),\s*([A-Za-z]{2})$")
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}

_last_nominatim_call = 0.0


def normalize_location_query(raw: str) -> str:
    """Normalize a location string for cache and built-in lookups."""
    cleaned = re.sub(r"\s+", " ", raw).strip().lower()
    # Strip trailing ", united states" / ", us" / ", usa" when checking built-ins.
    cleaned = re.sub(r",?\s*(united states|usa|us)$", "", cleaned).strip(" ,")
    zip_match = US_ZIP_RE.match(cleaned)
    if zip_match:
        return f"us_zip:{zip_match.group(1)}"
    return cleaned


def _split_multi_location(raw: str) -> list[str]:
    """Handle strings like 'San Francisco, CA • New York, NY' or 'California and New Mexico'."""
    for sep in (";", "|", "/", "•", " and "):
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            # Prefer a non-remote location if mixed with "Remote".
            for part in parts:
                if not NON_GEO_RE.match(part):
                    return [part]
            return parts[:1]
    return [raw.strip()]


def is_nationwide_location(location_text: str) -> bool:
    """Return True for US-wide / nationwide multi-site listings."""
    return bool(location_text and NATIONWIDE_RE.search(location_text))


def extract_us_state_code(location_text: str) -> str | None:
    """Extract a 2-letter US state code from strings like 'Albemarle, NC 28001, US' or 'Austin, TX'."""
    if not location_text:
        return None
    # Check ', ST' or ' ST 12345' patterns.
    match = re.search(r",\s*([A-Z]{2})(?:\s+\d{5})?(?:\s*,|\s*$)", location_text)
    if match and match.group(1) in US_STATE_CODE_TO_NAME:
        return match.group(1)
    lowered = location_text.strip().lower()
    for state_code, state_name in US_STATE_CODE_TO_NAME.items():
        if state_name.lower() == lowered:
            return state_code
    return None


def location_matches_state(item_location: str, state_code: str) -> bool:
    """Return True if a posting's location matches the user's US state (by full name or code)."""
    if not item_location or not state_code:
        return False
    state_name = US_STATE_CODE_TO_NAME.get(state_code.upper())
    if not state_name:
        return False
    lowered = item_location.lower()
    if re.search(rf"\b{re.escape(state_name.lower())}\b", lowered):
        return True
    if re.search(rf",\s*{re.escape(state_code.lower())}\b", lowered):
        return True
    return False


def geocode_location(
    db: Database,
    raw_query: str,
    allow_network: bool = True,
) -> tuple[float, float, str] | None:
    """Resolve a city, state, or ZIP code to (lat, lon, display_name) without API keys."""
    if not raw_query:
        return None
    primary = _split_multi_location(raw_query)[0]
    if NON_GEO_RE.match(primary):
        return None

    norm = normalize_location_query(primary)
    if not norm:
        return None

    if norm in BUILTIN_LOCATIONS:
        return BUILTIN_LOCATIONS[norm]

    if norm in US_STATE_CENTROIDS:
        return US_STATE_CENTROIDS[norm]

    # Check substring match against city name before hitting network (e.g. "austin" -> "austin, tx").
    for key, coords in BUILTIN_LOCATIONS.items():
        city_only = key.split(",")[0]
        if norm == city_only:
            return coords

    cached = db.fetchone(
        "SELECT latitude, longitude, display_name FROM geocode_cache WHERE query_norm = ?",
        (norm,),
    )
    if cached is not None:
        return (
            float(cached["latitude"]),
            float(cached["longitude"]),
            str(cached["display_name"]),
        )

    if not allow_network:
        return None

    return _query_nominatim_and_cache(db, norm, primary)


def build_nominatim_params(norm: str, query: str) -> dict[str, str]:
    """Build Nominatim search parameters, scoping 5-digit ZIPs and US City, ST queries to the US."""
    base: dict[str, str] = {"format": "json", "limit": "1", "addressdetails": "1"}
    if norm.startswith("us_zip:"):
        zip5 = norm.split(":", 1)[1]
        return {**base, "postalcode": zip5, "countrycodes": "us"}
    city_state = US_CITY_STATE_RE.match(query.strip())
    if city_state and city_state.group(2).upper() in US_STATE_CODES:
        return {**base, "q": query.strip(), "countrycodes": "us"}
    return {**base, "q": query.strip()}


def _format_nominatim_display(top: dict, fallback: str) -> str:
    addr = top.get("address")
    if isinstance(addr, dict):
        locality = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("hamlet")
            or addr.get("county")
        )
        state = addr.get("ISO3166-2-lvl4", "")
        if isinstance(state, str) and state.startswith("US-"):
            state = state[3:]
        else:
            state = addr.get("state") or ""
        postcode = addr.get("postcode") or ""
        country_code = str(addr.get("country_code") or "").upper()
        parts = [p for p in (locality, state) if p]
        if parts:
            label = ", ".join(parts)
            if postcode and country_code == "US":
                label = f"{label} {postcode}"
            if country_code:
                label = f"{label}, {country_code}"
            return label
    return str(top.get("display_name") or fallback)


def _query_nominatim_and_cache(
    db: Database,
    norm: str,
    query: str,
) -> tuple[float, float, str] | None:
    global _last_nominatim_call
    elapsed = time.monotonic() - _last_nominatim_call
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)

    try:
        _last_nominatim_call = time.monotonic()
        params = build_nominatim_params(norm, query)
        with build_http_client(
            timeout=6.0,
            headers={"User-Agent": "HighSchoolInternshipScreener/1.0 (local-dev)"},
        ) as client:
            resp = client.get(
                "https://nominatim.openstreetmap.org/search",
                params=params,
            )
            resp.raise_for_status()
            results = resp.json()
        if not results:
            return None
        top = results[0]
        lat = float(top["lat"])
        lon = float(top["lon"])
        display = _format_nominatim_display(top, query)
        db.execute(
            """
            INSERT OR REPLACE INTO geocode_cache (query_norm, display_name, latitude, longitude, cached_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (norm, display, lat, lon, utc_now_iso()),
        )
        return (lat, lon, display)
    except Exception:
        return None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in miles between two WGS84 coordinates."""
    earth_radius_miles = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * earth_radius_miles * math.asin(min(1.0, math.sqrt(a)))
