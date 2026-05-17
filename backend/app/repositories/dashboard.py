from __future__ import annotations

import sqlite3


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

