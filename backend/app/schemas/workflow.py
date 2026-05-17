from __future__ import annotations

from backend.app.schemas.common import APIModel


class StatusDefinition(APIModel):
    id: int
    status_code: str
    status_name: str
    description: str | None = None
    entry_condition: str | None = None
    exit_condition: str | None = None
    responsible_role: str | None = None
    key_deliverable: str | None = None
    is_terminal: int
    sort_order: int
    color: str
    is_active: int


class TransitionRule(APIModel):
    id: int
    from_status: str
    to_status: str
    action_name: str
    requires_approval: int
    approver_role: str | None = None
    required_deliverable: str | None = None
    is_active: int
    to_status_name: str | None = None


class MermaidDiagram(APIModel):
    diagram: str

