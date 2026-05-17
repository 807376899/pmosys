from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from backend.app.schemas.common import APIModel, PagedResponse


class ProjectType(str, Enum):
    teaching_software = "teaching_software"
    practical_teaching_site = "practical_teaching_site"


PROJECT_TYPE_META: dict[ProjectType, dict[str, str]] = {
    ProjectType.teaching_software: {"label": "教学软件", "prefix": "SW"},
    ProjectType.practical_teaching_site: {"label": "实践教学场所", "prefix": "SY"},
}

PATCHABLE_PROJECT_FIELDS = {
    "name",
    "description",
    "department",
    "sponsor",
    "project_manager",
    "category",
    "project_type",
    "budget",
    "special_note",
    "actual_start_date",
    "actual_end_date",
}


class ProjectBase(APIModel):
    name: str
    description: str = ""
    department: str = ""
    sponsor: str = ""
    project_manager: str = ""
    category: str = ""
    project_type: ProjectType
    budget: float = 0
    special_note: str = ""
    actual_start_date: str = ""
    actual_end_date: str = ""


class ProjectCreate(ProjectBase):
    project_code: str = ""
    approved_budget: float | None = None
    operator: str = Field(min_length=1)

    @field_validator("name", "operator")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class ProjectUpdate(APIModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    department: str | None = None
    sponsor: str | None = None
    project_manager: str | None = None
    category: str | None = None
    project_type: ProjectType | None = None
    budget: float | None = None
    special_note: str | None = None
    actual_start_date: str | None = None
    actual_end_date: str | None = None

    def cleaned_updates(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ProjectListItem(APIModel):
    id: int
    project_code: str
    name: str
    description: str | None = None
    department: str | None = None
    sponsor: str | None = None
    project_manager: str | None = None
    current_status: str
    category: str | None = None
    project_type: ProjectType | None = None
    budget: float | None = None
    approved_budget: float | None = None
    special_note: str | None = None
    actual_start_date: str | None = None
    actual_end_date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    status_updated_at: str | None = None


class ProjectDetail(ProjectListItem):
    pass


class ProjectListResponse(PagedResponse[ProjectListItem]):
    pass


class StatusHistoryItem(APIModel):
    id: int
    project_id: int
    from_status: str | None = None
    to_status: str
    action: str
    operator: str
    approver: str | None = None
    comment: str | None = None
    deliverable: str | None = None
    transition_date: str
    from_status_name: str | None = None
    to_status_name: str | None = None


class TransitionRequest(APIModel):
    to_status: str
    operator: str = Field(min_length=1)
    operator_role: str = "USER"
    approver: str | None = None
    comment: str = Field(min_length=1)
    deliverable: str = ""
    force: bool = False
    approved_budget: float | None = None
    expected_current_status: str | None = None
    expected_status_updated_at: str | None = None


class TransitionResponse(APIModel):
    success: bool
    message: str


class BatchTransitionPreviewRequest(APIModel):
    project_ids: list[int]
    operator_role: str = "USER"
    to_status: str
    force: bool = False
    expected_statuses: dict[int, str] | None = None
    expected_status_updated_at: dict[int, str] | None = None


class BatchTransitionPreviewConflict(APIModel):
    project_id: int
    project_code: str
    name: str
    code: str
    message: str


class BatchTransitionTarget(APIModel):
    to_status: str
    status_name: str
    requires_approval: bool
    approver_roles: list[str]
    action_names: list[str]


class BatchTransitionPreviewResponse(APIModel):
    total: int
    project_ids: list[int]
    available_targets: list[BatchTransitionTarget]
    requested_target: BatchTransitionTarget | None = None
    requires_approval: bool
    approved_budget_allowed: bool
    conflicts: list[BatchTransitionPreviewConflict]


class BatchTransitionExecuteRequest(APIModel):
    project_ids: list[int]
    to_status: str
    operator: str = Field(min_length=1)
    operator_role: str = "USER"
    approver: str | None = None
    comment: str = Field(min_length=1)
    deliverable: str = ""
    force: bool = False
    approved_budget: float | None = None
    expected_statuses: dict[int, str] | None = None
    expected_status_updated_at: dict[int, str] | None = None


class BatchTransitionErrorItem(APIModel):
    project_id: int
    project_code: str
    name: str
    code: str
    message: str


class BatchTransitionExecuteResponse(APIModel):
    total: int
    success: int
    failed: int
    errors: list[BatchTransitionErrorItem]
