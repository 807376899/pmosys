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

_STAGE_TERMINAL_STATUSES = "'closed','terminated'"
_STAGE_UNESTABLISHED_STATUSES = "'draft','under_review'"


def external_conditions_filter_condition(state: str, alias: str = "p") -> str | None:
    """One predicate for list/export external-condition views.

    A project is ready when it has no unresolved blocking constraint; an empty
    constraint set is therefore ready by design.
    """
    unresolved = (
        "EXISTS (SELECT 1 FROM project_external_constraints ec "
        f"WHERE ec.project_id={alias}.id AND ec.is_blocking=1 "
        "AND ec.clearance_status NOT IN ('cleared','not_applicable'))"
    )
    if state == "ongoing":
        return unresolved
    if state == "ready":
        return f"NOT {unresolved}"
    return None


def stage_group_condition(group: str, alias: str = "p") -> str | None:
    """Single SQL projection used by cards and list filters."""
    if group == "pre_establish":
        return f"{alias}.current_status IN ({_STAGE_UNESTABLISHED_STATUSES})"
    if group == "completed":
        return f"{alias}.current_status = 'closed'"
    if group == "abandoned":
        return f"{alias}.current_status = 'terminated'"
    base = f"{alias}.current_status NOT IN ({_STAGE_UNESTABLISHED_STATUSES},{_STAGE_TERMINAL_STATUSES})"
    if group == "pool_active":
        # "推进中" is a PMO management view, not a mutually-exclusive Stage.
        # Specially advanced unestablished projects stay in the 未立项 view too.
        return (
            f"(({base} AND COALESCE({alias}.library_implementation_view, 'unimplemented') = 'advancing') "
            f"OR ({alias}.current_status IN ({_STAGE_UNESTABLISHED_STATUSES}) "
            f"AND COALESCE({alias}.special_advancement_active, 0) = 1))"
        )
    if group == "pool_pending":
        return f"({base} AND COALESCE({alias}.library_implementation_view, 'unimplemented') != 'advancing')"
    return None


def insert_project(conn: sqlite3.Connection, payload: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO projects (
            project_code, name, description, department, sponsor, project_manager,
            current_status, category, project_type, budget, approved_budget,
            contract_amount, special_note, actual_start_date, actual_end_date, major, location, procurement_nature
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            payload.get("major", ""),
            payload.get("location", ""),
            payload.get("procurement_nature", ""),
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
    row = conn.execute("SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)).fetchone()
    return dict(row) if row else None


def fetch_project_any_by_id(conn: sqlite3.Connection, project_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def restore_project(conn: sqlite3.Connection, project_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE projects SET deleted_at=NULL, deleted_by='', deleted_reason='' WHERE id=? AND deleted_at IS NOT NULL",
        (project_id,),
    )
    return cursor.rowcount > 0


def fetch_projects_by_ids(conn: sqlite3.Connection, project_ids: list[int]) -> list[dict]:
    if not project_ids:
        return []
    placeholders = ",".join("?" for _ in project_ids)
    rows = conn.execute(
        f"SELECT * FROM projects WHERE id IN ({placeholders}) AND deleted_at IS NULL ORDER BY id",
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


def delete_project(conn: sqlite3.Connection, project_id: int, operator: str, reason: str) -> bool:
    cursor = conn.execute(
        "UPDATE projects SET deleted_at=?, deleted_by=?, deleted_reason=? WHERE id=? AND deleted_at IS NULL",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), operator, reason, project_id),
    )
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


def _order_clause(filters: dict) -> str:
    sort_by = filters.get("sort_by") or "status_updated_at"
    sort_dir = "ASC" if filters.get("sort_dir") == "asc" else "DESC"
    department_order = list(filters.get("department_order") or [])
    legacy_cases: list[str] = []
    for index, department in enumerate(department_order):
        escaped = department.replace("'", "''")
        legacy_cases.append(f"WHEN p.department = '{escaped}' THEN {index}")
    legacy_department_cases = " ".join(legacy_cases)
    legacy_department_rank = f"CASE {legacy_department_cases} ELSE {len(department_order)} END" if legacy_department_cases else "0"
    mapping = {
        "project_type": "CASE WHEN pt.sort_order IS NULL THEN 1 ELSE 0 END, pt.sort_order, p.project_type, CASE WHEN ds.sort_order IS NULL THEN 1 ELSE 0 END, ds.sort_order, p.department",
        "current_status": "p.current_status",
        "department": f"CASE WHEN ds.sort_order IS NULL THEN 1 ELSE 0 END, ds.sort_order, {legacy_department_rank}, p.department",
        "category": f"CASE WHEN pc.sort_order IS NULL THEN 1 ELSE 0 END, pc.sort_order, p.category, CASE WHEN ds.sort_order IS NULL THEN 1 ELSE 0 END, ds.sort_order, {legacy_department_rank}, p.department",
        "implementation_year": "substr(p.actual_start_date, 1, 4)",
        "status_updated_at": "p.status_updated_at",
    }
    expression = mapping.get(sort_by, "status_updated_at")
    if sort_by in {"department", "category", "project_type"}:
        return f"ORDER BY {expression} {sort_dir}, p.name {sort_dir}, p.project_code {sort_dir}"
    if sort_by == "implementation_year":
        return f"ORDER BY COALESCE(NULLIF({expression}, ''), '0000') {sort_dir}, updated_at DESC, id DESC"
    return f"ORDER BY {expression} {sort_dir}, p.updated_at DESC, p.id DESC"


def fetch_project_page(conn: sqlite3.Connection, filters: dict) -> tuple[list[dict], int]:
    # The only caller setting include_deleted is the PMO "已移除项目" view.
    # Keep that view focused on recoverable projects instead of mixing active rows
    # back into it.
    conditions: list[str] = ["p.deleted_at IS NOT NULL"] if filters.get("include_deleted") else ["p.deleted_at IS NULL"]
    params: list[object] = []
    if filters.get("status"):
        conditions.append("current_status = ?")
        params.append(filters["status"])
    if filters.get("group"):
        condition = stage_group_condition(filters["group"])
        if condition:
            conditions.append(condition)
    if filters.get("advancement_status") == "special_active":
        conditions.append("special_advancement_active = 1")
    external_condition = external_conditions_filter_condition(str(filters.get("external_conditions") or ""))
    if external_condition:
        conditions.append(external_condition)
    if filters.get("keyword"):
        conditions.append(
            "(name LIKE ? OR project_code LIKE ? OR description LIKE ? OR sponsor LIKE ? OR special_note LIKE ?)"
        )
        like_value = f"%{filters['keyword']}%"
        params.extend([like_value] * 5)
    for field in ("department", "project_manager", "category"):
        value = filters.get(field)
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)
    if filters.get("project_type"):
        conditions.append("CASE project_type WHEN 'teaching_software' THEN 'software' WHEN 'practical_teaching_site' THEN 'laboratory' ELSE project_type END = ?")
        params.append({"teaching_software": "software", "practical_teaching_site": "laboratory"}.get(filters["project_type"], filters["project_type"]))
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
    total = conn.execute(f"SELECT COUNT(*) FROM projects p{where_clause}", params).fetchone()[0]
    page = max(int(filters.get("page", 1)), 1)
    page_size = max(min(int(filters.get("page_size", 20)), 200), 1)
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"""
        SELECT p.* FROM projects p
        LEFT JOIN project_categories pc ON pc.name = p.category
        LEFT JOIN project_types pt ON pt.code = p.project_type
        LEFT JOIN department_settings ds ON ds.department = p.department
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
    conditions: list[str] = ["p.deleted_at IS NULL"]
    params: list[object] = []
    if export_filters.get("status"):
        conditions.append("current_status = ?")
        params.append(export_filters["status"])
    if export_filters.get("group"):
        condition = stage_group_condition(export_filters["group"])
        if condition:
            conditions.append(condition)
    if export_filters.get("advancement_status") == "special_active":
        conditions.append("special_advancement_active = 1")
    external_condition = external_conditions_filter_condition(str(export_filters.get("external_conditions") or ""))
    if external_condition:
        conditions.append(external_condition)
    if export_filters.get("keyword"):
        conditions.append(
            "(name LIKE ? OR project_code LIKE ? OR description LIKE ? OR sponsor LIKE ? OR special_note LIKE ?)"
        )
        like_value = f"%{export_filters['keyword']}%"
        params.extend([like_value] * 5)
    for field in ("department", "project_manager", "category"):
        value = export_filters.get(field)
        if value:
            conditions.append(f"{field} = ?")
            params.append(value)
    if export_filters.get("project_type"):
        conditions.append("CASE project_type WHEN 'teaching_software' THEN 'software' WHEN 'practical_teaching_site' THEN 'laboratory' ELSE project_type END = ?")
        params.append({"teaching_software": "software", "practical_teaching_site": "laboratory"}.get(export_filters["project_type"], export_filters["project_type"]))
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
        SELECT p.* FROM projects p
        LEFT JOIN project_categories pc ON pc.name = p.category
        LEFT JOIN project_types pt ON pt.code = p.project_type
        LEFT JOIN department_settings ds ON ds.department = p.department
        {where_clause}
        {_order_clause(export_filters)}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
