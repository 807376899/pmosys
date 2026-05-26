from __future__ import annotations

import sqlite3

from backend.app.repositories.projects import GROUP_STATUS_MAP


def fetch_budget_summary(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_projects,
            COALESCE(SUM(budget), 0) AS total_budget,
            COALESCE(SUM(approved_budget), 0) AS total_approved_budget,
            COALESCE(SUM(contract_amount), 0) AS total_contract_amount
        FROM projects
        """
    ).fetchone()
    return dict(row)


def fetch_project_library_summary(
    conn: sqlite3.Connection,
    library_statuses: list[str],
    review_status: str,
    reviewed_statuses: list[str],
) -> dict:
    library_placeholders = ",".join("?" for _ in library_statuses)
    reviewed_placeholders = ",".join("?" for _ in reviewed_statuses)
    row = conn.execute(
        f"""
        SELECT
            COALESCE(SUM(CASE WHEN current_status IN ({library_placeholders}) THEN 1 ELSE 0 END), 0)
                AS project_library_count,
            COALESCE(SUM(CASE WHEN current_status IN ({library_placeholders}) THEN budget ELSE 0 END), 0)
                AS project_library_total_budget,
            COALESCE(SUM(CASE WHEN current_status = ? THEN 1 ELSE 0 END), 0)
                AS review_in_progress_count,
            COALESCE(SUM(
                CASE WHEN current_status IN ({reviewed_placeholders}) AND approved_budget IS NOT NULL THEN 1 ELSE 0 END
            ), 0) AS reviewed_count,
            COALESCE(SUM(
                CASE WHEN current_status IN ({reviewed_placeholders}) AND approved_budget IS NOT NULL
                    THEN approved_budget
                    ELSE 0
                END
            ), 0)
                AS reviewed_total_approved_budget
        FROM projects
        """,
        [*library_statuses, *library_statuses, review_status, *reviewed_statuses, *reviewed_statuses],
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
                COALESCE(SUM(approved_budget), 0) AS total_approved_budget,
                COALESCE(SUM(contract_amount), 0) AS total_contract_amount
            FROM projects
            WHERE current_status IN ({placeholders})
            """,
            statuses,
        ).fetchone()
        summaries[key] = dict(row)
    return summaries
