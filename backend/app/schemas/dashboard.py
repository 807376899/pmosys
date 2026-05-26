from __future__ import annotations

from backend.app.schemas.common import APIModel


class StatusStat(APIModel):
    status_code: str
    status_name: str
    color: str
    is_terminal: int
    project_count: int


class DashboardSummary(APIModel):
    total_projects: int
    total_budget: float
    total_approved_budget: float
    total_contract_amount: float
    project_library_count: int
    project_library_total_budget: float
    review_in_progress_count: int
    reviewed_count: int
    reviewed_total_approved_budget: float
    status_stats: list[StatusStat]


class DashboardGroupItem(APIModel):
    key: str
    label: str
    statuses: list[str]
    count: int
    total_budget: float
    total_approved_budget: float
    total_contract_amount: float
