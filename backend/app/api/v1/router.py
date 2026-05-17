from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1.dashboard import router as dashboard_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.imports_exports import router as import_export_router
from backend.app.api.v1.metadata import router as metadata_router
from backend.app.api.v1.projects import router as projects_router
from backend.app.api.v1.workflow import router as workflow_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(projects_router)
api_router.include_router(workflow_router)
api_router.include_router(dashboard_router)
api_router.include_router(metadata_router)
api_router.include_router(import_export_router)
