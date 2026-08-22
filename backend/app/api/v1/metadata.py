from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body

from backend.app.core.errors import ValidationError

from backend.app.db.connection import get_connection
from backend.app.core.config import get_settings
from backend.app.repositories.metadata import fetch_departments, fetch_project_managers


router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/departments", response_model=list[str])
def departments():
    with get_connection() as conn:
        return fetch_departments(conn, list(get_settings().department_order))


@router.get("/project-managers", response_model=list[str])
def project_managers():
    with get_connection() as conn:
        return fetch_project_managers(conn)


@router.get("/project-categories")
def project_categories(include_archived: bool = False):
    with get_connection() as conn:
        where = "" if include_archived else "WHERE is_active=1"
        return [dict(row) for row in conn.execute(
            f"SELECT * FROM project_categories {where} ORDER BY sort_order IS NULL, sort_order, name"
        ).fetchall()]


@router.post("/project-categories")
def create_project_category(payload: dict = Body(...)):
    name, operator = str(payload.get("name") or "").strip(), str(payload.get("operator") or "").strip()
    if not name or not operator:
        raise ValidationError("分类名称和操作人不能为空")
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO project_categories (name,sort_order,is_active) VALUES (?,?,?)",
            (name, payload.get("sort_order"), int(bool(payload.get("is_active", True)))),
        )
        return dict(conn.execute("SELECT * FROM project_categories WHERE name=?", (name,)).fetchone())


@router.patch("/project-categories/{category_id}")
def update_project_category(category_id: int, payload: dict = Body(...)):
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    updates = {key: value for key, value in payload.items() if key in {"name", "sort_order", "is_active"}}
    if not updates:
        raise ValidationError("没有可更新的分类字段")
    updates["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE project_categories SET {assignments} WHERE id=?", [*updates.values(), category_id])
        row = conn.execute("SELECT * FROM project_categories WHERE id=?", (category_id,)).fetchone()
        if not row:
            raise ValidationError("项目分类不存在")
        return dict(row)


@router.get("/department-settings")
def department_settings():
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM department_settings ORDER BY sort_order IS NULL, sort_order, department"
        ).fetchall()]


@router.patch("/departments/{department}/order")
def update_department_order(department: str, payload: dict = Body(...)):
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    if payload.get("sort_order") is None:
        raise ValidationError("请提供部门排序值")
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO department_settings (department,sort_order,updated_at) VALUES (?,?,?)
            ON CONFLICT(department) DO UPDATE SET sort_order=excluded.sort_order,updated_at=excluded.updated_at""",
            (department, int(payload["sort_order"]), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        return dict(conn.execute("SELECT * FROM department_settings WHERE department=?", (department,)).fetchone())
