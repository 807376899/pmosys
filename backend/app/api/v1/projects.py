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
    execute_batch_transition,
    get_project,
    get_project_history,
    list_projects,
    preview_batch_transition,
    transition_project_by_id,
    update_project,
)


router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
def get_projects(filters: Annotated[dict, Depends(project_filters)]):
    return list_projects(filters)


@router.post("", response_model=ProjectDetail)
def post_project(payload: Annotated[ProjectCreate, Body(openapi_examples={"default": {"value": PROJECT_CREATE_EXAMPLE}})]):
    return create_project(payload.model_dump())


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: int):
    return get_project(project_id)


@router.patch("/{project_id}", response_model=ProjectDetail)
def patch_project(project_id: int, payload: ProjectUpdate):
    return update_project(project_id, payload)


@router.delete("/{project_id}")
def remove_project(project_id: int):
    delete_project(project_id)
    return {"success": True}


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

