from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from backend.app.schemas.common import APIModel, PagedResponse


class ProjectType(str, Enum):
    """历史导入兼容枚举；新建项目运行时使用数据库类型目录。"""

    teaching_software = "teaching_software"
    practical_teaching_site = "practical_teaching_site"


PROJECT_TYPE_META = {
    ProjectType.teaching_software: {"label": "专业教学软件项目", "prefix": "SW"},
    ProjectType.practical_teaching_site: {"label": "实践教学场所项目", "prefix": "SY"},
}


PATCHABLE_PROJECT_FIELDS = {
    "name",
    "description",
    "department",
    "sponsor",
    "project_manager",
    "category",
    "project_type",
    "major",
    "location",
    "procurement_nature",
    "establishment_document_no",
    "budget",
    "contract_amount",
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
    project_type: str
    major: str = ""
    location: str = ""
    procurement_nature: str = ""
    budget: float = 0
    contract_amount: float | None = None
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
    project_type: str | None = None
    major: str | None = None
    location: str | None = None
    procurement_nature: str | None = None
    establishment_document_no: str | None = None
    budget: float | None = None
    contract_amount: float | None = None
    special_note: str | None = None
    actual_start_date: str | None = None
    actual_end_date: str | None = None
    operator: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    def cleaned_updates(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True, exclude={"operator", "reason"})


class ProjectDeleteRequest(APIModel):
    operator: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ProjectListItem(APIModel):
    id: int
    project_code: str
    name: str
    description: str | None = None
    department: str | None = None
    sponsor: str | None = None
    project_manager: str | None = None
    current_status: str | None = None
    category: str | None = None
    project_type: str | None = None
    major: str | None = None
    location: str | None = None
    procurement_nature: str | None = None
    project_summary_display: str | None = None
    establishment_document_no: str | None = None
    library_implementation_view: str | None = None
    budget: float | None = None
    approved_budget: float | None = None
    contract_amount: float | None = None
    special_note: str | None = None
    actual_start_date: str | None = None
    actual_end_date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    status_updated_at: str | None = None
    stage: str | None = None
    work_item_summary: list[dict[str, Any]] = Field(default_factory=list)
    work_item_count: int = 0
    active_work_item_count: int = 0
    work_item_states: dict[str, str] = Field(default_factory=dict)
    work_item_column_states: list[dict[str, Any]] = Field(default_factory=list)
    next_key_node: dict[str, Any] | None = None
    progress_focus_item: dict[str, Any] | None = None
    advancement: dict[str, Any] | None = None
    external_constraints_cleared: str | None = None
    external_constraint_count: int = 0
    external_constraint_open_count: int = 0
    external_constraint_states: list[dict[str, Any]] = []
    external_constraint_scope_confirmation: dict[str, Any] | None = None
    effective_budget: float | None = None
    effective_budget_source: str | None = None


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
