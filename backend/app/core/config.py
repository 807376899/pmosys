from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]


@dataclass(slots=True)
class AppSettings:
    app_name: str = "PMO Project Management API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    default_cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    sqlite_timeout: int = 30
    sqlite_busy_timeout_ms: int = 5000
    db_path: Path = field(default_factory=lambda: ROOT_DIR / "pmo.db")


def get_settings() -> AppSettings:
    default_settings = AppSettings()
    db_path = Path(os.environ.get("PMO_DB_PATH", str(default_settings.db_path)))
    return AppSettings(db_path=db_path)
