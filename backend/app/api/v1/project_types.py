from fastapi import APIRouter, Body, Query

from backend.app.core.errors import ValidationError
from backend.app.db.connection import get_connection

router = APIRouter(prefix="/project-types", tags=["project-types"])


@router.get("")
def get_project_types(include_inactive: bool = Query(False)):
    with get_connection() as conn:
        where = "" if include_inactive else "WHERE is_active = 1"
        rows = conn.execute(f"SELECT id, code, name, code_prefix, is_active, sort_order FROM project_types {where} ORDER BY sort_order IS NULL, sort_order, id").fetchall()
    return [dict(row) for row in rows]


@router.post("")
def create_project_type(payload: dict = Body(...)):
    name = str(payload.get("name") or "").strip()
    prefix = str(payload.get("code_prefix") or "").strip().upper()
    operator = str(payload.get("operator") or "").strip()
    if not name or not prefix or not operator:
        raise ValidationError("分类名称、编号前缀和操作人不能为空")
    with get_connection() as conn:
        code = str(payload.get("code") or "").strip()
        if not code:
            next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM project_types").fetchone()[0]
            code = f"custom_{next_id}"
        conn.execute("INSERT INTO project_types (code,name,code_prefix,is_active,sort_order) VALUES (?,?,?,?,?)", (code, name, prefix, 1, payload.get("sort_order")))
        return dict(conn.execute("SELECT id,code,name,code_prefix,is_active,sort_order FROM project_types WHERE code=?", (code,)).fetchone())


@router.patch("/{type_id}")
def update_project_type(type_id: int, payload: dict = Body(...)):
    operator = str(payload.get("operator") or "").strip()
    if not operator:
        raise ValidationError("操作人不能为空")
    updates = {key: payload[key] for key in ("name", "is_active", "sort_order") if key in payload}
    if not updates:
        raise ValidationError("没有可更新的分类字段")
    with get_connection() as conn:
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(f"UPDATE project_types SET {assignments} WHERE id=?", [*updates.values(), type_id])
        row = conn.execute("SELECT id,code,name,code_prefix,is_active,sort_order FROM project_types WHERE id=?", (type_id,)).fetchone()
        if not row:
            raise ValidationError("项目分类不存在")
        return dict(row)
