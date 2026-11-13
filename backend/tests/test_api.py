"""Integration tests for FastAPI endpoints and geo-radius filtering."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import SqliteDatabase, init_schema
from app.geocoder import (
    build_nominatim_params,
    geocode_location,
    is_nationwide_location,
    location_matches_state,
    normalize_location_query,
)
from app.main import create_app


def _make_test_client(tmp_path: Path, secret: str = "") -> tuple[TestClient, SqliteDatabase]:
    db = SqliteDatabase(":memory:")
    init_schema(db)
    settings = Settings(
        database_path=tmp_path / "unused.db",
        turso_database_url="",
        turso_auth_token="",
        scan_trigger_secret=secret,
        cors_origins=("http://localhost:5173",),
        sources_file=tmp_path / "missing.json",
    )
    app = create_app(settings=settings, db_override=db, allow_geocode_network=False)
    return TestClient(app), db


def test_email_ingest_and_area_radius_filtering(tmp_path: Path):
    client, db = _make_test_client(tmp_path)
    try:
        with client:
            raw_alert = """
<html><body>
  <div>
    <a href="https://www.linkedin.com/comm/jobs/view/1001/?trk=test">High School Biotech Intern</a>
    <div>BioLab Austin</div>
    <div>Austin, TX</div>
    <div>Paid $20/hr internship for high school juniors and seniors.</div>
  </div>
  <div>
    <a href="https://www.linkedin.com/comm/jobs/view/1002/?trk=test">Remote High School Web Intern</a>
    <div>OpenWeb Nonprofit</div>
    <div>Remote</div>
    <div>Stipend available for high school students grades 10-12.</div>
  </div>
  <div>
    <a href="https://www.linkedin.com/comm/jobs/view/1003/?trk=test">High School Robotics Intern</a>
    <div>Lakefront Robotics</div>
    <div>Chicago, IL</div>
    <div>Open to high school students in Chicago.</div>
  </div>
</body></html>
"""
            resp = client.post("/api/ingest/email", json={"raw_email": raw_alert})
            assert resp.status_code == 200
            data = resp.json()
            assert data["parsed_count"] == 3
            assert data["eligible"] == 3

            # Search Austin within 25 miles + remote included => Austin + Remote (not Chicago).
            search_resp = client.get(
                "/api/internships",
                params={"area": "Austin, TX", "radius_miles": 25, "include_remote": True},
            )
            assert search_resp.status_code == 200
            payload = search_resp.json()
            assert payload["area_resolved"]["display_name"] == "Austin, TX"
            titles = [item["title"] for item in payload["items"]]
            assert "High School Biotech Intern" in titles
            assert "Remote High School Web Intern" in titles
            assert "High School Robotics Intern" not in titles

            # Exclude remote => only Austin.
            in_person_resp = client.get(
                "/api/internships",
                params={"area": "Austin, TX", "radius_miles": 25, "include_remote": False},
            )
            assert [i["title"] for i in in_person_resp.json()["items"]] == [
                "High School Biotech Intern"
            ]
    finally:
        db.close()


def test_sources_crud_ssrf_guard_and_scan_secret(tmp_path: Path):
    client, db = _make_test_client(tmp_path, secret="top-secret")
    try:
        with client:
            # SSRF guard blocks localhost RSS URLs.
            bad_rss = client.post(
                "/api/sources",
                json={
                    "name": "Bad Local",
                    "source_type": "rss",
                    "target": "http://127.0.0.1:8080/feed.xml",
                },
            )
            assert bad_rss.status_code == 400

            good = client.post(
                "/api/sources",
                json={
                    "name": "Local School RSS",
                    "source_type": "rss",
                    "target": "https://example.org/internships.xml",
                    "area_hint": "Austin, TX",
                },
            )
            assert good.status_code == 201
            source_id = good.json()["id"]

            toggled = client.patch(f"/api/sources/{source_id}", json={"enabled": False})
            assert toggled.status_code == 200
            assert toggled.json()["enabled"] == 0

            # Scan endpoint enforces SCAN_TRIGGER_SECRET when configured.
            unauth_scan = client.post("/api/scan")
            assert unauth_scan.status_code == 401

            auth_scan = client.post(
                "/api/scan",
                headers={"Authorization": "Bearer top-secret"},
            )
            assert auth_scan.status_code == 200
            assert auth_scan.json()["sources_scanned"] == 0  # Disabled above

            deleted = client.delete(f"/api/sources/{source_id}")
            assert deleted.status_code == 204
    finally:
        db.close()


def test_geocoder_skips_placeholders_and_splits_bullets():
    db = SqliteDatabase(":memory:")
    init_schema(db)
    try:
        assert geocode_location(db, "In-Office", allow_network=False) is None
        assert geocode_location(db, "Hybrid", allow_network=False) is None
        coords = geocode_location(db, "San Francisco, CA • New York, NY", allow_network=False)
        assert coords is not None
        assert coords[2] == "San Francisco, CA"
    finally:
        db.close()


def test_us_zip_and_city_state_scope_nominatim_to_usa():
    zip_norm = normalize_location_query("28001")
    assert zip_norm == "us_zip:28001"
    zip_params = build_nominatim_params(zip_norm, "28001")
    assert zip_params["postalcode"] == "28001"
    assert zip_params["countrycodes"] == "us"

    city_norm = normalize_location_query("Princeton, NJ")
    city_params = build_nominatim_params(city_norm, "Princeton, NJ")
    assert city_params["countrycodes"] == "us"

    intl_norm = normalize_location_query("London, UK")
    intl_params = build_nominatim_params(intl_norm, "London, UK")
    assert "countrycodes" not in intl_params


def test_statewide_and_nationwide_location_matching():
    assert location_matches_state("North Carolina", "NC")
    assert location_matches_state("California and New Mexico", "NM")
    assert not location_matches_state("South Carolina", "NC")
    assert is_nationwide_location("Across the US")
    assert is_nationwide_location("Nationwide (US)")

    db = SqliteDatabase(":memory:")
    init_schema(db)
    try:
        alb = geocode_location(db, "Albany, NY", allow_network=False)
        sch = geocode_location(db, "Schenectady, NY", allow_network=False)
        assert alb is not None and alb[2] == "Albany, NY"
        assert sch is not None and sch[2] == "Schenectady, NY"
    finally:
        db.close()
