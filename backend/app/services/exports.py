from __future__ import annotations

import io

import pandas as pd

from backend.app.db.connection import get_connection
from backend.app.repositories.projects import fetch_all_projects_for_export
from backend.app.schemas.project import PROJECT_TYPE_META, ProjectType
from backend.app.services.workflow import get_statuses


def _status_name_map() -> dict[str, str]:
    return {item["status_code"]: item["status_name"] for item in get_statuses()}


def export_projects(filters: dict) -> bytes:
    with get_connection() as conn:
        projects = fetch_all_projects_for_export(conn, filters)
    status_name_map = _status_name_map()
    rows = []
    for project in projects:
        project_type = project.get("project_type")
        rows.append(
            {
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "项目类型": PROJECT_TYPE_META[ProjectType(project_type)]["label"] if project_type else "",
                "当前状态": status_name_map.get(project["current_status"], project["current_status"]),
                "部门": project.get("department") or "",
                "项目负责人": project.get("project_manager") or "",
                "发起人": project.get("sponsor") or "",
                "项目分类": project.get("category") or "",
                "初始预算": project.get("budget") or 0,
                "审核后预算": project.get("approved_budget"),
                "状态更新时间": project.get("status_updated_at") or "",
                "特殊说明": project.get("special_note") or "",
                "项目描述": project.get("description") or "",
                "创建时间": project.get("created_at") or "",
                "更新时间": project.get("updated_at") or "",
            }
        )
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="项目列表")
    output.seek(0)
    return output.getvalue()

