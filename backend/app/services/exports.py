from __future__ import annotations

import io

import pandas as pd

from backend.app.db.connection import get_connection
from backend.app.core.config import get_settings
from backend.app.repositories.projects import fetch_all_projects_for_export
from backend.app.services.projects import _hydrate_project_projection


def export_projects(filters: dict) -> bytes:
    filters = {**filters, "department_order": list(get_settings().department_order)}
    with get_connection() as conn:
        projects = fetch_all_projects_for_export(conn, filters)
        projects = [_hydrate_project_projection(conn, project) for project in projects]
        type_names = {
            row["code"]: row["name"]
            for row in conn.execute("SELECT code, name FROM project_types").fetchall()
        }
    rows = []
    for project in projects:
        project_type = project.get("project_type")
        rows.append(
            {
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "项目分类": type_names.get(project_type, project_type or ""),
                "采购属性": {"goods": "货物", "service": "服务", "mixed": "混合"}.get(project.get("procurement_nature"), ""),
                "地点": project.get("location") or "",
                "Stage": project["stage"],
                "当前进展": "；".join(f"{item['name']}·{item['status']}" for item in project["work_item_summary"]),
                "下一关键节点": (project["next_key_node"] or {}).get("name", ""),
                "外部推进条件": project["external_constraints_cleared"],
                "部门": project.get("department") or "",
                "项目负责人": project.get("project_manager") or "",
                "发起人": project.get("sponsor") or "",
                "初始预算": project.get("budget") or 0,
                "审核后预算": project.get("approved_budget"),
                "当前有效预算": project.get("effective_budget"),
                "有效预算来源": project.get("effective_budget_source"),
                "合同金额": project.get("contract_amount"),
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
