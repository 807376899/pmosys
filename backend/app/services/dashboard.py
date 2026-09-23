from __future__ import annotations

from backend.app.db.connection import get_connection
from backend.app.repositories.dashboard import (
    fetch_budget_summary,
    fetch_project_library_summary,
)
from backend.app.repositories.projects import GROUP_STATUS_MAP
from backend.app.services.workflow import get_status_stats
from backend.app.services.projects import _hydrate_project_projection
from backend.app.core.money import parse_money, total


GROUP_LABELS = {
    "pre_establish": "未立项",
    "pool_pending": "项目库-未实施",
    "pool_active": "推进中",
    "completed": "已完成",
    "abandoned": "已废弃",
}

PROJECT_LIBRARY_STATUSES = [
    "established",
    "submission_review",
    "procuring",
    "implementing",
    "trial",
    "accepting",
    "suspended",
]
REVIEW_IN_PROGRESS_STATUS = "submission_review"
REVIEWED_STATUSES = ["established", "procuring", "implementing", "trial", "accepting"]


def get_dashboard_summary() -> dict:
    with get_connection() as conn:
        summary = fetch_budget_summary(conn)
        summary.update(
            fetch_project_library_summary(
                conn,
                PROJECT_LIBRARY_STATUSES,
                REVIEW_IN_PROGRESS_STATUS,
                REVIEWED_STATUSES,
            )
        )
        projections = []
        for row in conn.execute("SELECT * FROM projects WHERE deleted_at IS NULL").fetchall():
            projections.append(_hydrate_project_projection(conn, dict(row)))
    library = [item for item in projections if item["stage"] in {"项目库—未实施", "项目库—推进中"}]
    ready = [item for item in library if item["external_constraints_cleared"] == "true"]
    ongoing = [item for item in library if item["external_constraints_cleared"] == "false"]
    summary.update({
        "project_library_total_effective_budget": total(item["effective_budget"] for item in library),
        "external_conditions_ready_count": len(ready),
        "external_conditions_ready_effective_budget": total(item["effective_budget"] for item in ready),
        "external_conditions_ongoing_count": len(ongoing),
        "external_conditions_ongoing_effective_budget": total(item["effective_budget"] for item in ongoing),
    })
    # SQLite REAL aggregates are only a legacy compatibility path.  Every
    # current aggregate is rebuilt from the Decimal-backed project projection.
    summary.update({
        "total_budget": total(item["budget"] for item in projections),
        "total_approved_budget": total(item["approved_budget"] for item in projections),
        "total_contract_amount": total(item["contract_amount"] for item in projections),
        "project_library_total_budget": total(item["budget"] for item in library),
        "reviewed_total_approved_budget": total(
            item["approved_budget"] for item in projections
            if item.get("current_status") in REVIEWED_STATUSES
        ),
    })
    summary["status_stats"] = get_status_stats()
    return summary


def get_dashboard_groups() -> list[dict]:
    with get_connection() as conn:
        projections = [
            _hydrate_project_projection(conn, dict(row))
            for row in conn.execute("SELECT * FROM projects WHERE deleted_at IS NULL").fetchall()
        ]

    def belongs_to_group(key: str, item: dict) -> bool:
        if key == "pool_active":
            return item.get("advancement", {}).get("status") in {"active", "special_active"}
        if key == "pool_pending":
            return item.get("stage") == "项目库—未实施"
        if key == "pre_establish":
            return item.get("stage") == "未立项"
        if key == "completed":
            return item.get("stage") == "已完成"
        return item.get("stage") == "已废弃"

    items = []
    for key, statuses in GROUP_STATUS_MAP.items():
        group = [item for item in projections if belongs_to_group(key, item)]
        items.append(
            {
                "key": key,
                "label": GROUP_LABELS[key],
                "statuses": statuses,
                "count": len(group),
                "total_budget": total(item["budget"] for item in group),
                "total_approved_budget": total(item["approved_budget"] for item in group),
                "total_contract_amount": total(item["contract_amount"] for item in group),
            }
        )
    return items
