from __future__ import annotations

import sqlite3


def fetch_departments(conn: sqlite3.Connection, department_order: list[str] | None = None) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT department FROM projects WHERE department IS NOT NULL AND department != ''"
    ).fetchall()
    departments = [row["department"] for row in rows]
    order_map = {department: index for index, department in enumerate(department_order or [])}
    return sorted(departments, key=lambda item: (order_map.get(item, len(order_map)), item))


def fetch_project_managers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT project_manager FROM projects WHERE project_manager IS NOT NULL AND project_manager != '' ORDER BY project_manager"
    ).fetchall()
    return [row["project_manager"] for row in rows]
