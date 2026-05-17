from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.app.core.config import get_settings


def get_db_path() -> Path:
    return get_settings().db_path


def ensure_db_directory(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def create_connection() -> sqlite3.Connection:
    settings = get_settings()
    db_path = get_db_path()
    ensure_db_directory(db_path)
    conn = sqlite3.connect(db_path, timeout=settings.sqlite_timeout, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
    conn.execute("BEGIN")
    return conn


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = create_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

