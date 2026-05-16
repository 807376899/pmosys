from __future__ import annotations

import io

import pandas as pd

from lib.database import VALID_STATUS_CODES
from utils.formatters import get_status_name, get_status_order_map


def build_export_bytes(projects: list[dict]) -> bytes:
    """导出当前项目列表为 Excel。"""
    export_rows = []
    for project in projects:
        export_rows.append(
            {
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "当前状态": get_status_name(project["current_status"]),
                "申报部门": project.get("department") or "",
                "项目负责人": project.get("project_manager") or "",
                "发起人": project.get("sponsor") or "",
                "项目分类": project.get("category") or "",
                "初始申报预算(万元)": project.get("budget") or 0,
                "审核后预算(万元)": project.get("approved_budget"),
                "状态更新时间": project.get("status_updated_at") or "",
                "特殊说明": project.get("special_note") or "",
                "项目描述": project.get("description") or "",
                "创建时间": project.get("created_at") or "",
                "更新时间": project.get("updated_at") or "",
            }
        )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(export_rows).to_excel(writer, index=False, sheet_name="项目列表")
    output.seek(0)
    return output.getvalue()


def build_batch_failure_export_bytes(errors: list[dict]) -> bytes:
    """导出批量失败清单。"""
    output = io.BytesIO()
    rows = []
    for item in errors:
        rows.append(
            {
                "项目ID": item.get("project_id"),
                "项目编号": item.get("project_code"),
                "项目名称": item.get("name"),
                "失败原因": item.get("error"),
            }
        )

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="失败清单")
    output.seek(0)
    return output.getvalue()


def generate_import_template() -> bytes:
    """生成批量导入模板。"""
    template_data = [
        {
            "项目编号": "PMO-2026-0001",
            "项目名称": "示例项目1（编号可留空自动生成）",
            "项目描述": "这是一个示例项目描述",
            "申报部门": "信息中心",
            "发起人": "张主任",
            "项目负责人": "李工",
            "当前状态": "draft",
            "项目分类": "信息化建设",
            "预算(万元)": 100.0,
            "审核后预算(万元)": "",
            "特殊说明": "政策调整，本项目允许跳过送审",
            "实际开始日期": "",
            "实际结束日期": "",
        },
        {
            "项目编号": "",
            "项目名称": "示例项目2（编号留空将自动生成）",
            "项目描述": "另一个示例",
            "申报部门": "财务部",
            "发起人": "王主任",
            "项目负责人": "赵工",
            "当前状态": "submission_review",
            "项目分类": "基础设施",
            "预算(万元)": 200.0,
            "审核后预算(万元)": 180.0,
            "特殊说明": "",
            "实际开始日期": "2025-06-01",
            "实际结束日期": "",
        },
    ]

    instructions_data = [
        {"字段名": "项目编号", "说明": "项目唯一编号，留空则自动生成(PMO-年份-序号)", "是否必填": "否", "示例": "PMO-2026-0001"},
        {"字段名": "项目名称", "说明": "项目名称", "是否必填": "是", "示例": "智慧办公平台升级"},
        {"字段名": "项目描述", "说明": "项目简要描述", "是否必填": "否", "示例": "对现有办公平台进行智能化升级"},
        {"字段名": "申报部门", "说明": "项目申报部门", "是否必填": "否", "示例": "信息中心"},
        {"字段名": "发起人", "说明": "项目发起人", "是否必填": "否", "示例": "张主任"},
        {"字段名": "项目负责人", "说明": "项目负责人", "是否必填": "否", "示例": "李工"},
        {"字段名": "当前状态", "说明": "支持英文状态码或中文名称，非法值默认回退为草稿", "是否必填": "否(默认draft)", "示例": "draft / 草稿"},
        {"字段名": "项目分类", "说明": "项目分类", "是否必填": "否", "示例": "信息化建设"},
        {"字段名": "预算(万元)", "说明": "初始申报预算", "是否必填": "否(默认0)", "示例": "100.0"},
        {"字段名": "审核后预算(万元)", "说明": "送审后最终预算，可为空", "是否必填": "否", "示例": "95.0"},
        {"字段名": "特殊说明", "说明": "记录政策变化、跳过送审等特殊情况", "是否必填": "否", "示例": "政策变更，允许直接采购"},
        {"字段名": "实际开始日期", "说明": "格式 YYYY-MM-DD", "是否必填": "否", "示例": "2025-06-01"},
        {"字段名": "实际结束日期", "说明": "格式 YYYY-MM-DD", "是否必填": "否", "示例": "2025-12-31"},
    ]

    status_rows = []
    for status_code in VALID_STATUS_CODES:
        status_rows.append({"状态码": status_code, "中文名": get_status_name(status_code)})
    status_rows.sort(key=lambda item: get_status_order_map().get(item["状态码"], 999))

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(instructions_data).to_excel(writer, index=False, sheet_name="字段说明")
        pd.DataFrame(status_rows).to_excel(writer, index=False, sheet_name="合法状态列表")
        pd.DataFrame(template_data).to_excel(writer, index=False, sheet_name="导入模板(请复制此sheet)")
    output.seek(0)
    return output.getvalue()
