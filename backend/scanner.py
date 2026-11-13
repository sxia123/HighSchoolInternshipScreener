"""CLI scanner invoked locally or by GitHub Actions cron."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.db import create_database
from app.email_parser import parse_linkedin_alert_email
from app.ingest import run_scan, upsert_postings


def ingest_email_directory(db, email_dir: Path, default_area: str) -> dict[str, int]:
    """Scan a directory of .eml LinkedIn job alert files and upsert matches."""
    if not email_dir.is_dir():
        return {"files": 0, "fetched": 0, "upserted": 0, "eligible": 0, "possible": 0, "rejected": 0}

    files = sorted(email_dir.glob("*.eml"))
    all_postings = []
    for file_path in files:
        raw = file_path.read_text(encoding="utf-8", errors="replace")
        all_postings.extend(parse_linkedin_alert_email(raw, default_area=default_area))

    stats = upsert_postings(db, all_postings)
    return {"files": len(files), **stats}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan configured sources and screen high school internships."
    )
    parser.add_argument(
        "--trigger",
        default="cli",
        help="Trigger label recorded in scan_runs (e.g., cli, github_actions).",
    )
    parser.add_argument(
        "--emails-dir",
        type=Path,
        default=None,
        help="Optional directory containing .eml LinkedIn job alert files to ingest.",
    )
    parser.add_argument(
        "--default-area",
        default="",
        help="Default city/state hint for alert emails missing explicit locations.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    db = create_database(settings, initialize=True)
    try:
        summary: dict[str, object] = {
            "database_backend": db.backend_name,
            "scan": run_scan(db, trigger=args.trigger),
        }
        if args.emails_dir is not None:
            summary["emails"] = ingest_email_directory(
                db,
                email_dir=args.emails_dir,
                default_area=args.default_area,
            )
        print(json.dumps(summary, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
