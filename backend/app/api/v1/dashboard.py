from __future__ import annotations

from fastapi import APIRouter

from backend.app.schemas.dashboard import DashboardGroupItem, DashboardSummary
from backend.app.services.dashboard import get_dashboard_groups, get_dashboard_summary


router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def summary():
    return get_dashboard_summary()


@router.get("/groups", response_model=list[DashboardGroupItem])
def groups():
    return get_dashboard_groups()

