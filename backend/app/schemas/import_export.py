from __future__ import annotations

from backend.app.schemas.common import APIModel
from backend.app.schemas.project import ProjectType


class ImportPreviewRecord(APIModel):
    row_number: int
    project_code: str
    name: str
    description: str = ""
    department: str = ""
    sponsor: str = ""
    project_manager: str = ""
    current_status: str = "draft"
    category: str = ""
    project_type: ProjectType
    budget: float = 0
    approved_budget: float | None = None
    special_note: str = ""
    actual_start_date: str = ""
    actual_end_date: str = ""


class ImportPreviewErrorItem(APIModel):
    row_number: int
    code: str
    message: str
    name: str | None = None


class ImportPreviewResponse(APIModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    records: list[ImportPreviewRecord]
    errors: list[ImportPreviewErrorItem]


class ImportCommitRequest(APIModel):
    records: list[ImportPreviewRecord]
    operator: str


class ImportCommitErrorItem(APIModel):
    row_number: int
    name: str
    code: str
    message: str


class ImportCommitResponse(APIModel):
    total: int
    success: int
    failed: int
    errors: list[ImportCommitErrorItem]
