from __future__ import annotations

from backend.app.db.connection import get_connection
from backend.app.repositories.dashboard import fetch_budget_summary, fetch_group_budget_summaries
from backend.app.repositories.projects import GROUP_STATUS_MAP
from backend.app.services.workflow import get_status_stats


GROUP_LABELS = {
    "pre_establish": "未立项",
    "pool_pending": "项目库-未实施",
    "pool_active": "项目库-实施中",
    "completed": "已完成",
    "abandoned": "已废弃",
}


def get_dashboard_summary() -> dict:
    with get_connection() as conn:
        summary = fetch_budget_summary(conn)
    summary["status_stats"] = get_status_stats()
    return summary


def get_dashboard_groups() -> list[dict]:
    with get_connection() as conn:
        budget_summaries = fetch_group_budget_summaries(conn)

    status_counts = {item["status_code"]: item["project_count"] for item in get_status_stats()}
    items = []
    for key, statuses in GROUP_STATUS_MAP.items():
        summary = budget_summaries.get(
            key,
            {"count": 0, "total_budget": 0.0, "total_approved_budget": 0.0},
        )
        items.append(
            {
                "key": key,
                "label": GROUP_LABELS[key],
                "statuses": statuses,
                "count": int(summary["count"] if summary["count"] is not None else sum(status_counts.get(status, 0) for status in statuses)),
                "total_budget": float(summary["total_budget"] or 0),
                "total_approved_budget": float(summary["total_approved_budget"] or 0),
            }
        )
    return items
