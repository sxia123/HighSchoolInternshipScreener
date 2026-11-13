"""Application configuration loaded from environment and optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_if_present(env_path: Path) -> None:
    """Populate os.environ from a .env file without overriding existing variables."""
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    database_path: Path
    turso_database_url: str
    turso_auth_token: str
    scan_trigger_secret: str
    cors_origins: tuple[str, ...]
    sources_file: Path

    @property
    def use_turso(self) -> bool:
        return bool(self.turso_database_url and self.turso_auth_token)


def get_settings() -> Settings:
    """Read current settings from environment variables."""
    _load_dotenv_if_present(BACKEND_DIR / ".env")

    raw_db_path = os.getenv("DATABASE_PATH", "data/internships.db").strip()
    db_path = Path(raw_db_path)
    if not db_path.is_absolute():
        db_path = BACKEND_DIR / db_path

    raw_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = tuple(o.strip() for o in raw_origins.split(",") if o.strip())

    return Settings(
        database_path=db_path,
        turso_database_url=os.getenv("TURSO_DATABASE_URL", "").strip(),
        turso_auth_token=os.getenv("TURSO_AUTH_TOKEN", "").strip(),
        scan_trigger_secret=os.getenv("SCAN_TRIGGER_SECRET", "").strip(),
        cors_origins=origins,
        sources_file=BACKEND_DIR / "sources.json",
    )
