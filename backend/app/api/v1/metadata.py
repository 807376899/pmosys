from __future__ import annotations

from fastapi import APIRouter

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
