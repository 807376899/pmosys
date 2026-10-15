from __future__ import annotations

import sqlite3


def fetch_departments(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT p.department
           FROM projects p
           LEFT JOIN department_settings ds ON ds.department = p.department
           WHERE p.department IS NOT NULL AND p.department != ''
           ORDER BY CASE WHEN ds.sort_order IS NULL THEN 1 ELSE 0 END,
                    ds.sort_order,
                    p.department"""
    ).fetchall()
    return [row["department"] for row in rows]


def fetch_project_managers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT project_manager FROM projects WHERE project_manager IS NOT NULL AND project_manager != '' ORDER BY project_manager"
    ).fetchall()
    return [row["project_manager"] for row in rows]
