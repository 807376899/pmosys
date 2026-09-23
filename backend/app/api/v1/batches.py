from fastapi import APIRouter, Body, Query

from backend.app.services.batches import (
    add_work_item_batch_members, apply_work_item_batch_follow_up, complete_work_item_batch,
    create_work_item_batch, get_work_item_batch, list_work_item_batches, remove_work_item_batch_members,
    update_work_item_batch, void_work_item_batch,
)


router = APIRouter(prefix="/work-item-batches", tags=["work-item-batches"])


@router.post("")
def post_work_item_batch(payload: dict = Body(...)):
    return create_work_item_batch(payload)


@router.get("")
def get_work_item_batches(status: str | None = None, work_item_name: str | None = None, project_id: int | None = None,
                          year: int | None = None, keyword: str | None = None):
    return {"items": list_work_item_batches({"status": status, "work_item_name": work_item_name, "project_id": project_id, "year": year, "keyword": keyword})}


@router.get("/{batch_id}")
def get_one_work_item_batch(batch_id: int):
    return get_work_item_batch(batch_id)


@router.patch("/{batch_id}")
def patch_work_item_batch(batch_id: int, payload: dict = Body(...)):
    return update_work_item_batch(batch_id, payload)


@router.post("/{batch_id}/members")
def post_work_item_batch_members(batch_id: int, payload: dict = Body(...)):
    return add_work_item_batch_members(batch_id, payload)


@router.post("/{batch_id}/members/remove")
def post_remove_work_item_batch_members(batch_id: int, payload: dict = Body(...)):
    return remove_work_item_batch_members(batch_id, payload)


@router.post("/{batch_id}/complete")
def post_complete_work_item_batch(batch_id: int, payload: dict = Body(...)):
    return complete_work_item_batch(batch_id, payload)


@router.post("/{batch_id}/follow-up")
def post_work_item_batch_follow_up(batch_id: int, payload: dict = Body(...)):
    return apply_work_item_batch_follow_up(batch_id, payload)


@router.post("/{batch_id}/void")
def post_void_work_item_batch(batch_id: int, payload: dict = Body(...)):
    return void_work_item_batch(batch_id, payload)
