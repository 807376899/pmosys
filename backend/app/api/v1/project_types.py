from fastapi import APIRouter

from backend.app.db.connection import get_connection

router = APIRouter(prefix="/project-types", tags=["project-types"])


@router.get("")
def get_project_types():
    with get_connection() as conn:
        rows = conn.execute("SELECT id, code, name, code_prefix, is_active FROM project_types WHERE is_active = 1 ORDER BY id").fetchall()
    return [dict(row) for row in rows]
