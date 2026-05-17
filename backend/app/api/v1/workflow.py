from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.schemas.workflow import MermaidDiagram, StatusDefinition, TransitionRule
from backend.app.services import workflow as workflow_service


router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.get("/statuses", response_model=list[StatusDefinition])
def get_statuses():
    return workflow_service.get_statuses()


@router.get("/transitions", response_model=list[TransitionRule])
def get_transitions():
    return workflow_service.get_transition_rules()


@router.get("/transitions/allowed", response_model=list[TransitionRule])
def get_allowed(from_status: str = Query(...)):
    return workflow_service.get_allowed_transitions(from_status)


@router.get("/diagram", response_model=MermaidDiagram)
def get_diagram():
    return {"diagram": workflow_service.generate_mermaid_diagram()}

