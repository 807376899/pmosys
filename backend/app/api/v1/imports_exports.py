from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import StreamingResponse

from backend.app.api.deps import project_filters
from backend.app.schemas.import_export import (
    ImportCommitRequest,
    ImportCommitResponse,
    ImportPreviewResponse,
)
from backend.app.services.exports import export_projects
from backend.app.services.imports import commit_import, generate_import_template, preview_import


router = APIRouter(tags=["imports-exports"])


@router.get("/imports/projects/template")
def import_template():
    content = generate_import_template()
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="project_import_template.xlsx"'},
    )


@router.post("/imports/projects/preview", response_model=ImportPreviewResponse)
async def import_preview(file: UploadFile = File(...)):
    content = await file.read()
    return preview_import(file.filename or "upload.xlsx", content)


@router.post("/imports/projects/commit", response_model=ImportCommitResponse)
def import_commit(payload: ImportCommitRequest):
    return commit_import(payload.records, payload.operator)


@router.get("/exports/projects")
def projects_export(filters: dict = Depends(project_filters)):
    content = export_projects(filters)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="projects_export.xlsx"'},
    )
