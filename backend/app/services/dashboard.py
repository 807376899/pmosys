from __future__ import annotations

from backend.app.db.connection import get_connection
from backend.app.repositories.dashboard import fetch_budget_summary
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
    stats = {item["status_code"]: item["project_count"] for item in get_status_stats()}
    items = []
    for key, statuses in GROUP_STATUS_MAP.items():
        items.append(
            {
                "key": key,
                "label": GROUP_LABELS[key],
                "statuses": statuses,
                "count": sum(stats.get(status, 0) for status in statuses),
            }
        )
    return items

