from __future__ import annotations

import sqlite3
from datetime import datetime


GROUP_STATUS_MAP = {
    "pre_establish": ["draft", "under_review"],
    "pool_pending": ["established", "submission_review"],
    "pool_active": ["procuring", "implementing", "trial", "accepting", "suspended"],
    "completed": ["closed"],
    "abandoned": ["terminated"],
}


def insert_project(conn: sqlite3.Connection, payload: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO projects (
            project_code, name, description, department, sponsor, project_manager,
            current_status, category, project_type, budget, approved_budget,
            contract_amount, special_note, actual_start_date, actual_end_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["project_code"],
            payload["name"],
            payload.get("description", ""),
            payload.get("department", ""),
            payload.get("sponsor", ""),
            payload.get("project_manager", ""),
            payload.get("current_status", "draft"),
            payload.get("category", ""),
            payload.get("project_type"),
            payload.get("budget", 0),
            payload.get("approved_budget"),
            payload.get("contract_amount"),
            payload.get("special_note", ""),
            payload.get("actual_start_date", ""),
            payload.get("actual_end_date", ""),
        ),
    )
    return int(cursor.lastrowid)


def insert_status_history(
    conn: sqlite3.Connection,
    *,
    project_id: int,
    from_status: str | None,
    to_status: str,
    action: str,
    operator: str,
    approver: str | None = None,
    comment: str | None = None,
    deliverable: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO status_history (
            project_id, from_status, to_status, action, operator, approver, comment, deliverable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, from_status, to_status, action, operator, approver, comment, deliverable),
    )


def fetch_project_by_id(conn: sqlite3.Connection, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def fetch_projects_by_ids(conn: sqlite3.Connection, project_ids: list[int]) -> list[dict]:
    if not project_ids:
        return []
    placeholders = ",".join("?" for _ in project_ids)
    rows = conn.execute(
        f"SELECT * FROM projects WHERE id IN ({placeholders}) ORDER BY id",
        project_ids,
    ).fetchall()
    return [dict(row) for row in rows]


def project_code_exists(conn: sqlite3.Connection, project_code: str) -> bool:
    row = conn.execute("SELECT 1 FROM projects WHERE project_code = ?", (project_code,)).fetchone()
    return bool(row)


def fetch_max_project_code(conn: sqlite3.Connection, prefix: str, year: int) -> str | None:
    like_value = f"{prefix}{year}%"
    row = conn.execute(
        "SELECT MAX(project_code) FROM projects WHERE project_code LIKE ?",
        (like_value,),
    ).fetchone()
    return row[0]


def update_project_fields(conn: sqlite3.Connection, project_id: int, updates: dict) -> bool:
    payload = updates.copy()
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{field} = ?" for field in payload)
    params = list(payload.values()) + [project_id]
    cursor = conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", params)
    return cursor.rowcount > 0


def delete_project(conn: sqlite3.Connection, project_id: int) -> bool:
    cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return cursor.rowcount > 0


def update_project_status(conn: sqlite3.Connection, project_id: int, updates: dict) -> None:
    set_clause = ", ".join(f"{field} = ?" for field in updates)
    params = list(updates.values()) + [project_id]
    conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", params)


def fetch_status_history(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT sh.*,
               sf.status_name AS from_status_name,
               st.status_name AS to_status_name
        FROM status_history sh
        LEFT JOIN status_definitions sf ON sf.status_code = sh.from_status
        LEFT JOIN status_definitions st ON st.status_code = sh.to_status
        WHERE sh.project_id = ?
        ORDER BY sh.transition_date ASC
        """,
        (project_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _department_order_expression(department_order: list[str]) -> str:
    if not department_order:
        return "department"
    clauses = []
    for index, department in enumerate(department_order):
        escaped = department.replace("'", "''")
        clauses.append(f"WHEN department = '{escaped}' THEN {index}")
    cases = " ".join(clauses)
    return f"CASE {cases} ELSE {len(department_order)} END, department"


def _order_clause(filters: dict) -> str:
    sort_by = filters.get("sort_by") or "status_updated_at"
    sort_dir = "ASC" if filters.get("sort_dir") == "asc" else "DESC"
    department_order = list(filters.get("department_order") or [])
    mapping = {
        "project_type": "project_type",
        "current_status": "current_status",
        "department": _department_order_expression(department_order),
        "implementation_year": "substr(actual_start_date, 1, 4)",
        "status_updated_at": "status_updated_at",
    }
    expression = mapping.get(sort_by, "status_updated_at")
    if sort_by == "department":
        return f"ORDER BY {expression} {sort_dir}, updated_at DESC, id DESC"
    if sort_by == "implementation_year":
        return f"ORDER BY COALESCE(NULLIF({expression}, ''), '0000') {sort_dir}, updated_at DESC, id DESC"
    return f"ORDER BY {expression} {sort_dir}, updated_at DESC, id DESC"


def fetch_project_page(conn: sqlite3.Connection, filters: dict) -> tuple[list[dict], int]:
    conditions: list[str] = []
    params: list[object] = []
    if filters.get("status"):
        conditions.append("current_status = ?")
        params.append(filters["status"])
    if filters.get("group"):
        statuses = GROUP_STATUS_MAP.get(filters["group"])
        if statuses:
            conditions.append(f"current_status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
    if filters.get("keyword"):
        conditions.append(
            "(name LIKE ? OR project_code LIKE ? OR description LIKE ? OR sponsor LIKE ? OR special_note LIKE ?)"
        )
        like_value = f"%{filters['keyword']}%"
        params.extend([like_value] * 5)
    for field in ("department", "project_manager", "project_type", "category"):
        value = filters.get(field)
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)
    if filters.get("min_budget") is not None:
        conditions.append("budget >= ?")
        params.append(filters["min_budget"])
    if filters.get("max_budget") is not None:
        conditions.append("budget <= ?")
        params.append(filters["max_budget"])
    if filters.get("status_updated_from"):
        conditions.append("status_updated_at >= ?")
        params.append(filters["status_updated_from"])
    if filters.get("status_updated_to"):
        conditions.append("status_updated_at <= ?")
        params.append(filters["status_updated_to"])
    if filters.get("declaration_year"):
        year = str(filters["declaration_year"])
        conditions.append(
            "(project_code LIKE ? OR project_code LIKE ? OR project_code LIKE ? OR substr(created_at, 1, 4) = ?)"
        )
        params.extend([f"SW{year}%", f"SY{year}%", f"PMO-{year}-%", year])
    if filters.get("implementation_year"):
        conditions.append("substr(actual_start_date, 1, 4) = ?")
        params.append(str(filters["implementation_year"]))

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) FROM projects{where_clause}", params).fetchone()[0]
    page = max(int(filters.get("page", 1)), 1)
    page_size = max(min(int(filters.get("page_size", 20)), 200), 1)
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT * FROM projects
        {where_clause}
        {_order_clause(filters)}
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()
    return [dict(row) for row in rows], int(total)


def fetch_all_projects_for_export(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    export_filters = dict(filters)
    export_filters.pop("page", None)
    export_filters.pop("page_size", None)
    conditions: list[str] = []
    params: list[object] = []
    if export_filters.get("status"):
        conditions.append("current_status = ?")
        params.append(export_filters["status"])
    if export_filters.get("group"):
        statuses = GROUP_STATUS_MAP.get(export_filters["group"])
        if statuses:
            conditions.append(f"current_status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
    if export_filters.get("keyword"):
        conditions.append(
            "(name LIKE ? OR project_code LIKE ? OR description LIKE ? OR sponsor LIKE ? OR special_note LIKE ?)"
        )
        like_value = f"%{export_filters['keyword']}%"
        params.extend([like_value] * 5)
    for field in ("department", "project_manager", "project_type", "category"):
        value = export_filters.get(field)
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)
    if export_filters.get("min_budget") is not None:
        conditions.append("budget >= ?")
        params.append(export_filters["min_budget"])
    if export_filters.get("max_budget") is not None:
        conditions.append("budget <= ?")
        params.append(export_filters["max_budget"])
    if export_filters.get("status_updated_from"):
        conditions.append("status_updated_at >= ?")
        params.append(export_filters["status_updated_from"])
    if export_filters.get("status_updated_to"):
        conditions.append("status_updated_at <= ?")
        params.append(export_filters["status_updated_to"])
    if export_filters.get("declaration_year"):
        year = str(export_filters["declaration_year"])
        conditions.append(
            "(project_code LIKE ? OR project_code LIKE ? OR project_code LIKE ? OR substr(created_at, 1, 4) = ?)"
        )
        params.extend([f"SW{year}%", f"SY{year}%", f"PMO-{year}-%", year])
    if export_filters.get("implementation_year"):
        conditions.append("substr(actual_start_date, 1, 4) = ?")
        params.append(str(export_filters["implementation_year"]))
    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT * FROM projects
        {where_clause}
        {_order_clause(export_filters)}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
