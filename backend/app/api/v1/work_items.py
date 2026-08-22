from __future__ import annotations

from fastapi import APIRouter, Body, Query

from backend.app.services.projects import (
    archive_template,
    create_work_item_template,
    create_work_package,
    create_external_constraint_template,
    list_external_constraint_templates,
    list_work_item_templates,
    list_work_packages,
    restore_template,
    delete_template_permanently,
    update_template,
)


router = APIRouter(tags=["work-items"])


@router.get("/work-item-templates")
def get_work_item_templates(keyword: str = Query(default=""), include_archived: bool = Query(default=False)):
    items = list_work_item_templates(include_archived)
    return [item for item in items if keyword.strip().lower() in item["name"].lower()]


@router.post("/work-item-templates")
def post_work_item_template(payload: dict = Body(...)):
    return create_work_item_template(payload)


@router.get("/external-constraint-templates")
def get_external_constraint_templates(keyword: str = Query(default=""), include_archived: bool = Query(default=False)):
    return list_external_constraint_templates(keyword, include_archived)


@router.post("/external-constraint-templates")
def post_external_constraint_template(payload: dict = Body(...)):
    return create_external_constraint_template(payload)


@router.post("/work-packages")
def post_work_package(payload: dict = Body(...)):
    return create_work_package(payload)


@router.get("/work-packages")
def get_work_packages(include_archived: bool = Query(default=False)):
    return list_work_packages(include_archived)


@router.patch("/work-packages/{template_id}")
def patch_work_package(template_id: int, payload: dict = Body(...)):
    return update_template("work_package", template_id, payload)


@router.post("/work-packages/{template_id}/archive")
def archive_work_package(template_id: int, payload: dict = Body(...)):
    return archive_template("work_package", template_id, payload)


@router.post("/work-packages/{template_id}/restore")
def restore_work_package(template_id: int, payload: dict = Body(...)):
    return restore_template("work_package", template_id, payload)


@router.delete("/work-packages/{template_id}")
def delete_work_package(template_id: int, payload: dict = Body(...)):
    return delete_template_permanently("work_package", template_id, payload)


@router.patch("/{template_kind}-templates/{template_id}")
def patch_template(template_kind: str, template_id: int, payload: dict = Body(...)):
    return update_template(template_kind, template_id, payload)


@router.post("/{template_kind}-templates/{template_id}/archive")
def archive_template_route(template_kind: str, template_id: int, payload: dict = Body(...)):
    return archive_template(template_kind, template_id, payload)


@router.post("/{template_kind}-templates/{template_id}/restore")
def restore_template_route(template_kind: str, template_id: int, payload: dict = Body(...)):
    return restore_template(template_kind, template_id, payload)


@router.delete("/{template_kind}-templates/{template_id}")
def delete_template_route(template_kind: str, template_id: int, payload: dict = Body(...)):
    return delete_template_permanently(template_kind, template_id, payload)
