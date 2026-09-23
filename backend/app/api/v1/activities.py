from fastapi import APIRouter, Body

from backend.app.services.activities import add_work_item_activity_members, create_work_item_activity, create_work_item_activity_progress_log, delete_work_item_activity_progress_log, end_work_item_activity, get_work_item_activity, list_work_item_activities, record_work_item_activity_results, remove_work_item_activity_members, start_work_item_activity, update_work_item_activity, update_work_item_activity_progress_log, void_work_item_activity

router = APIRouter(prefix="/work-item-activities", tags=["work-item-activities"])

@router.post("")
def post_activity(payload: dict = Body(...)): return create_work_item_activity(payload)

@router.get("")
def get_activities(status: str | None = None, work_item_name: str | None = None, project_id: int | None = None, year: int | None = None, keyword: str | None = None):
    return {"items": list_work_item_activities({"status": status, "work_item_name": work_item_name, "project_id": project_id, "year": year, "keyword": keyword})}

@router.get("/{activity_id}")
def get_activity(activity_id: int): return get_work_item_activity(activity_id)

@router.patch("/{activity_id}")
def patch_activity(activity_id: int, payload: dict = Body(...)): return update_work_item_activity(activity_id, payload)

@router.post("/{activity_id}/start")
def post_start(activity_id: int, payload: dict = Body(...)): return start_work_item_activity(activity_id, payload)

@router.post("/{activity_id}/end")
def post_end(activity_id: int, payload: dict = Body(...)): return end_work_item_activity(activity_id, payload)

@router.post("/{activity_id}/void")
def post_void(activity_id: int, payload: dict = Body(...)): return void_work_item_activity(activity_id, payload)

@router.post("/{activity_id}/members")
def post_members(activity_id: int, payload: dict = Body(...)): return add_work_item_activity_members(activity_id, payload)

@router.post("/{activity_id}/members/remove")
def post_remove_members(activity_id: int, payload: dict = Body(...)): return remove_work_item_activity_members(activity_id, payload)

@router.post("/{activity_id}/results")
def post_results(activity_id: int, payload: dict = Body(...)): return record_work_item_activity_results(activity_id, payload)

@router.post("/{activity_id}/progress-logs")
def post_progress_log(activity_id: int, payload: dict = Body(...)): return create_work_item_activity_progress_log(activity_id, payload)

@router.patch("/{activity_id}/progress-logs/{log_id}")
def patch_progress_log(activity_id: int, log_id: int, payload: dict = Body(...)): return update_work_item_activity_progress_log(activity_id, log_id, payload)

@router.delete("/{activity_id}/progress-logs/{log_id}")
def delete_progress_log(activity_id: int, log_id: int, payload: dict = Body(...)): return delete_work_item_activity_progress_log(activity_id, log_id, payload)
