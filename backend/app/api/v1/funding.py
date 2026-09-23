from __future__ import annotations

from fastapi import APIRouter, Body, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from backend.app.services.funding import (
    bulk_upsert_source_allocations,
    commit_funding_import,
    create_arrangement,
    create_source,
    delete_arrangement,
    delete_project_allocation,
    delete_source,
    funding_import_template,
    funding_overview,
    get_project_allocations,
    list_arrangements,
    list_sources,
    preview_funding_import,
    update_arrangement,
    update_source,
    upsert_project_allocation,
)


router = APIRouter(prefix="/funding", tags=["funding"])


@router.get("/overview")
def overview(year: int = Query(...)):
    return funding_overview(year)


@router.get("/arrangements")
def arrangements(year: int = Query(...)):
    return list_arrangements(year)


@router.post("/arrangements")
def post_arrangement(payload: dict = Body(...)):
    return create_arrangement(payload)


@router.patch("/arrangements/{arrangement_id}")
def patch_arrangement(arrangement_id: int, payload: dict = Body(...)):
    return update_arrangement(arrangement_id, payload)


@router.delete("/arrangements/{arrangement_id}")
def remove_arrangement(arrangement_id: int, payload: dict = Body(...)):
    delete_arrangement(arrangement_id, payload)
    return {"success": True}


@router.get("/sources")
def sources(year: int | None = Query(None)):
    return list_sources(year)


@router.post("/sources")
def post_source(payload: dict = Body(...)):
    return create_source(payload)


@router.patch("/sources/{source_id}")
def patch_source(source_id: int, payload: dict = Body(...)):
    return update_source(source_id, payload)


@router.delete("/sources/{source_id}")
def remove_source(source_id: int, payload: dict = Body(...)):
    delete_source(source_id, payload)
    return {"success": True}


@router.post("/sources/{source_id}/allocations")
def allocate_source(source_id: int, payload: dict = Body(...)):
    return bulk_upsert_source_allocations(source_id, payload)


@router.get("/allocations/import/template")
def allocation_import_template(year: int = Query(...)):
    return StreamingResponse(
        iter([funding_import_template(year)]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="funding_allocation_{year}.xlsx"'},
    )


@router.post("/allocations/import/preview")
async def allocation_import_preview(file: UploadFile = File(...), planning_year: int | None = Query(None)):
    return preview_funding_import(await file.read(), planning_year)


@router.post("/allocations/import/commit")
def allocation_import_commit(payload: dict = Body(...)):
    return commit_funding_import(
        payload.get("records") or [], str(payload.get("operator") or ""),
        bool(payload.get("confirm_source_amount_updates")), payload.get("planning_year"),
    )


project_router = APIRouter(prefix="/projects", tags=["funding"])


@project_router.get("/{project_id}/funding-allocations")
def project_allocations(project_id: int):
    return get_project_allocations(project_id)


@project_router.post("/{project_id}/funding-allocations")
def post_project_allocation(project_id: int, payload: dict = Body(...)):
    return upsert_project_allocation(project_id, payload)


@project_router.delete("/{project_id}/funding-allocations/{allocation_id}")
def remove_project_allocation(project_id: int, allocation_id: int, payload: dict = Body(...)):
    delete_project_allocation(project_id, allocation_id, payload)
    return {"success": True}
