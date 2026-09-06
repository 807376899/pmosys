from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query

from backend.app.api.deps import project_filters
from backend.app.docs.openapi_examples import PROJECT_CREATE_EXAMPLE, TRANSITION_EXAMPLE
from backend.app.schemas.project import (
    BatchTransitionExecuteRequest,
    BatchTransitionExecuteResponse,
    BatchTransitionPreviewRequest,
    BatchTransitionPreviewResponse,
    ProjectCreate,
    ProjectDeleteRequest,
    ProjectDetail,
    ProjectListResponse,
    ProjectUpdate,
    StatusHistoryItem,
    TransitionRequest,
    TransitionResponse,
)
from backend.app.services.projects import (
    create_project,
    delete_project,
    restore_project,
    execute_batch_transition,
    get_project,
    get_project_history,
    list_projects,
    preview_batch_transition,
    transition_project_by_id,
    update_project,
    pmo_override_project,
    complete_submission_review,
    create_work_item, complete_work_item, reopen_work_item, include_in_advancement, get_audit_events, get_work_items,
    batch_create_work_items, batch_include_in_advancement, batch_defer_advancement, apply_work_package, update_work_item, quick_update_work_item, reorder_main_work_items,
    create_progress_log, get_progress_logs, update_progress_log, delete_progress_log, get_management_timeline, cancel_work_item, skip_work_item,
    defer_advancement, complete_advancement_cycle, get_advancement_cycles, create_early_preparation, special_include_in_advancement,
    create_project_external_constraint, get_project_external_constraints, confirm_external_constraint_scope,
    act_on_project_external_constraint,
    batch_create_project_external_constraints,
    get_milestones,
)


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse, response_model_exclude_none=True)
def get_projects(filters: Annotated[dict, Depends(project_filters)]):
    return list_projects(filters)


@router.post("", response_model=ProjectDetail)
def post_project(payload: Annotated[ProjectCreate, Body(openapi_examples={"default": {"value": PROJECT_CREATE_EXAMPLE}})]):
    return create_project(payload.model_dump())


@router.post("/batch-work-items")
def batch_work_items(payload: dict = Body(...)):
    return batch_create_work_items(payload)


@router.post("/batch-external-constraints")
def batch_external_constraints(payload: dict = Body(...)):
    return batch_create_project_external_constraints(payload)


@router.post("/batch-include-in-advancement")
def batch_include_advancement(payload: dict = Body(...)):
    return batch_include_in_advancement(payload)

@router.post("/batch-defer-advancement")
def batch_defer(payload: dict = Body(...)):
    return batch_defer_advancement(payload)


@router.post("/apply-work-package")
def apply_package(payload: dict = Body(...)):
    return apply_work_package(payload)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: int):
    return get_project(project_id)


@router.patch("/{project_id}", response_model=ProjectDetail)
def patch_project(project_id: int, payload: ProjectUpdate):
    return update_project(project_id, payload)


@router.delete("/{project_id}")
def remove_project(project_id: int, payload: ProjectDeleteRequest):
    delete_project(project_id, payload.operator, payload.reason)
    return {"success": True, "soft_deleted": True}


@router.post("/{project_id}/restore", response_model=ProjectDetail)
def restore_removed_project(project_id: int, payload: ProjectDeleteRequest):
    return restore_project(project_id, payload.operator, payload.reason)


@router.get("/{project_id}/history", response_model=list[StatusHistoryItem])
def history(project_id: int):
    return get_project_history(project_id)


@router.post(
    "/{project_id}/transitions",
    response_model=TransitionResponse,
)
def transition(
    project_id: int,
    payload: Annotated[TransitionRequest, Body(openapi_examples={"default": {"value": TRANSITION_EXAMPLE}})],
):
    return transition_project_by_id(project_id, payload.model_dump())


@router.post("/batch-transition/preview", response_model=BatchTransitionPreviewResponse)
def batch_preview(payload: BatchTransitionPreviewRequest):
    return preview_batch_transition(payload.model_dump())


@router.post("/batch-transition", response_model=BatchTransitionExecuteResponse)
def batch_execute(payload: BatchTransitionExecuteRequest):
    return execute_batch_transition(payload.model_dump())


@router.post("/{project_id}/pmo-override", response_model=ProjectDetail)
def pmo_override(project_id: int, payload: dict = Body(...)):
    return pmo_override_project(project_id, payload)


@router.post("/{project_id}/submission-review-complete", response_model=ProjectDetail)
def submission_review_complete(project_id: int, payload: dict = Body(...)):
    return complete_submission_review(project_id, payload)

@router.post("/{project_id}/work-items")
def add_work_item(project_id: int, payload: dict = Body(...)):
    return create_work_item(project_id, payload)


@router.post("/{project_id}/work-items/reorder")
def reorder_work_items(project_id: int, payload: dict = Body(...)):
    return reorder_main_work_items(project_id, payload)

@router.get("/{project_id}/external-constraints")
def list_external_constraints(project_id: int):
    return get_project_external_constraints(project_id)


@router.post("/{project_id}/external-constraints")
def add_external_constraint(project_id: int, payload: dict = Body(...)):
    return create_project_external_constraint(project_id, payload)


@router.post("/{project_id}/external-constraints/{constraint_id}/actions")
def act_on_external_constraint(project_id: int, constraint_id: int, payload: dict = Body(...)):
    return act_on_project_external_constraint(project_id, constraint_id, payload)


@router.post("/{project_id}/confirm-external-constraint-scope")
def confirm_external_scope(project_id: int, payload: dict = Body(...)):
    return confirm_external_constraint_scope(project_id, payload)

@router.patch("/{project_id}/work-items/{item_id}")
def patch_work_item(project_id: int, item_id: int, payload: dict = Body(...)):
    return update_work_item(project_id, item_id, payload)


@router.post("/{project_id}/work-items/{item_id}/quick-update")
def quick_patch_work_item(project_id: int, item_id: int, payload: dict = Body(...)):
    return quick_update_work_item(project_id, item_id, payload)

@router.get("/{project_id}/work-items")
def list_work_items(project_id: int):
    return get_work_items(project_id)

@router.get("/{project_id}/milestones")
def milestones(project_id: int):
    return get_milestones(project_id)

@router.post("/{project_id}/work-items/{item_id}/complete")
def complete_item(project_id: int, item_id: int, payload: dict = Body(...)):
    return complete_work_item(project_id, item_id, payload)

@router.post("/{project_id}/work-items/{item_id}/reopen")
def reopen_item(project_id: int, item_id: int, payload: dict = Body(...)):
    return reopen_work_item(project_id, item_id, payload)

@router.post("/{project_id}/work-items/{item_id}/cancel")
def cancel_item(project_id: int, item_id: int, payload: dict = Body(...)):
    return cancel_work_item(project_id, item_id, payload)

@router.post("/{project_id}/work-items/{item_id}/skip")
def skip_item(project_id: int, item_id: int, payload: dict = Body(...)):
    return skip_work_item(project_id, item_id, payload)

@router.post("/{project_id}/work-items/{item_id}/progress-logs")
def add_progress_log(project_id: int, item_id: int, payload: dict = Body(...)):
    return create_progress_log(project_id, item_id, payload)

@router.get("/{project_id}/work-items/{item_id}/progress-logs")
def list_progress_logs(project_id: int, item_id: int):
    return get_progress_logs(project_id, item_id)


@router.patch("/{project_id}/work-items/{item_id}/progress-logs/{log_id}")
def patch_progress_log(project_id: int, item_id: int, log_id: int, payload: dict = Body(...)):
    return update_progress_log(project_id, item_id, log_id, payload)


@router.delete("/{project_id}/work-items/{item_id}/progress-logs/{log_id}")
def remove_progress_log(project_id: int, item_id: int, log_id: int, payload: dict = Body(...)):
    return delete_progress_log(project_id, item_id, log_id, payload)

@router.post("/{project_id}/include-in-advancement", response_model=ProjectDetail)
def include_advancement(project_id: int, payload: dict = Body(...)):
    return include_in_advancement(project_id, payload)

@router.post("/{project_id}/defer-advancement", response_model=ProjectDetail)
def defer_project_advancement(project_id: int, payload: dict = Body(...)):
    return defer_advancement(project_id, payload)

@router.post("/{project_id}/complete-advancement-cycle", response_model=ProjectDetail)
def complete_project_advancement_cycle(project_id: int, payload: dict = Body(...)):
    return complete_advancement_cycle(project_id, payload)

@router.get("/{project_id}/advancement-cycles")
def advancement_cycles(project_id: int):
    return get_advancement_cycles(project_id)

@router.post("/{project_id}/early-preparation")
def early_preparation(project_id: int, payload: dict = Body(...)):
    return create_early_preparation(project_id, payload)


@router.post("/{project_id}/special-include-in-advancement", response_model=ProjectDetail)
def special_include_advancement(project_id: int, payload: dict = Body(...)):
    return special_include_in_advancement(project_id, payload)

@router.get("/{project_id}/audit-events")
def audit_events(project_id: int):
    return get_audit_events(project_id)

@router.get("/{project_id}/management-timeline")
def management_timeline(project_id: int):
    return get_management_timeline(project_id)
