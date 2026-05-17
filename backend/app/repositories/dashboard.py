from __future__ import annotations

import sqlite3

from backend.app.repositories.projects import GROUP_STATUS_MAP


def fetch_budget_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_projects,
            COALESCE(SUM(budget), 0) AS total_budget,
            COALESCE(SUM(approved_budget), 0) AS total_approved_budget
        FROM projects
        """
    ).fetchone()
    return dict(row)


def fetch_group_budget_summaries(conn: sqlite3.Connection) -> dict[str, dict]:
    summaries: dict[str, dict] = {}
    for key, statuses in GROUP_STATUS_MAP.items():
        placeholders = ",".join("?" for _ in statuses)
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS count,
                COALESCE(SUM(budget), 0) AS total_budget,
                COALESCE(SUM(approved_budget), 0) AS total_approved_budget
            FROM projects
            WHERE current_status IN ({placeholders})
            """,
            statuses,
        ).fetchone()
        summaries[key] = dict(row)
    return summaries
