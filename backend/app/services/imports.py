from __future__ import annotations

import io
from typing import Any

import pandas as pd

from backend.app.core.errors import DuplicateProjectCodeError, ValidationError
from backend.app.db.connection import get_connection
from backend.app.repositories import projects as project_repo
from backend.app.schemas.import_export import ImportPreviewErrorItem, ImportPreviewRecord
from backend.app.schemas.project import ProjectType
from backend.app.services.project_codes import generate_project_code, validate_manual_project_code
from backend.app.services.projects import create_project_internal


VALID_STATUS_CODES = {
    "draft",
    "under_review",
    "established",
    "submission_review",
    "procuring",
    "implementing",
    "trial",
    "accepting",
    "closed",
    "suspended",
    "terminated",
}

STATUS_CN_TO_EN = {
    "草稿": "draft",
    "评审中": "under_review",
    "已立项": "established",
    "送审中": "submission_review",
    "采购中": "procuring",
    "实施中": "implementing",
    "试用中": "trial",
    "验收中": "accepting",
    "已关闭": "closed",
    "已暂停": "suspended",
    "已终止": "terminated",
}

PROJECT_TYPE_ALIASES = {
    "teaching_software": ProjectType.teaching_software,
    "教学软件": ProjectType.teaching_software,
    "practical_teaching_site": ProjectType.practical_teaching_site,
    "实践教学场所": ProjectType.practical_teaching_site,
}

FIELD_ALIASES = {
    "project_code": ["project_code", "项目编号"],
    "name": ["name", "项目名称"],
    "description": ["description", "项目描述"],
    "department": ["department", "申报部门", "部门"],
    "sponsor": ["sponsor", "发起人"],
    "project_manager": ["project_manager", "项目负责人", "负责人"],
    "current_status": ["current_status", "当前状态", "状态"],
    "category": ["category", "项目分类", "分类"],
    "project_type": ["project_type", "项目类型"],
    "budget": ["budget", "预算", "预算(万元)"],
    "approved_budget": ["approved_budget", "审核后预算", "审核后预算(万元)"],
    "contract_amount": ["contract_amount", "合同金额", "合同金额(万元)", "合同"],
    "special_note": ["special_note", "特殊说明"],
    "actual_start_date": ["actual_start_date", "实际开始", "实际开始日期"],
    "actual_end_date": ["actual_end_date", "实际结束", "实际结束日期"],
}


def _next_reserved_safe_code(conn, project_type: ProjectType, reserved_codes: set[str]) -> str:
    candidate = generate_project_code(conn, project_type)
    if candidate not in reserved_codes:
        return candidate
    prefix = candidate[:-4]
    seq = int(candidate[-4:]) + 1
    while True:
        generated = f"{prefix}{seq:04d}"
        if generated not in reserved_codes and not project_repo.project_code_exists(conn, generated):
            return generated
        seq += 1


def generate_import_template() -> bytes:
    rows = [
        {
            "项目编号": "",
            "项目名称": "智慧教室软件升级",
            "项目描述": "一期建设",
            "申报部门": "信息中心",
            "发起人": "张主任",
            "项目负责人": "李工",
            "当前状态": "draft",
            "项目分类": "信息化建设",
            "项目类型": "教学软件",
            "预算(万元)": 120,
            "审核后预算(万元)": "",
            "合同金额(万元)": "",
            "特殊说明": "",
            "实际开始日期": "",
            "实际结束日期": "",
        }
    ]
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="导入模板")
    output.seek(0)
    return output.getvalue()


def _read_table(file_name: str, content: bytes) -> pd.DataFrame:
    if file_name.lower().endswith(".csv"):
        return pd.read_csv(io.BytesIO(content), dtype=str).fillna("")
    return pd.read_excel(io.BytesIO(content), dtype=str).fillna("")


def _pick_value(row: dict[str, Any], aliases: list[str]) -> str:
    for alias in aliases:
        value = row.get(alias, "")
        if value not in ("", None):
            return str(value).strip()
    return ""


def preview_import(file_name: str, content: bytes) -> dict:
    df = _read_table(file_name, content)
    records: list[ImportPreviewRecord] = []
    errors: list[ImportPreviewErrorItem] = []
    reserved_codes: set[str] = set()
    with get_connection() as conn:
        for index, raw_row in enumerate(df.to_dict(orient="records"), start=1):
            try:
                name = _pick_value(raw_row, FIELD_ALIASES["name"])
                if not name:
                    raise ValidationError("项目名称不能为空")
                raw_type = _pick_value(raw_row, FIELD_ALIASES["project_type"])
                if raw_type not in PROJECT_TYPE_ALIASES:
                    raise ValidationError("项目类型必须为 教学软件 或 实践教学场所")
                project_type = PROJECT_TYPE_ALIASES[raw_type]
                project_code = _pick_value(raw_row, FIELD_ALIASES["project_code"])
                if project_code:
                    project_code = validate_manual_project_code(project_code, project_type)
                    if project_repo.project_code_exists(conn, project_code) or project_code in reserved_codes:
                        raise DuplicateProjectCodeError(f"项目编号重复: {project_code}")
                else:
                    project_code = _next_reserved_safe_code(conn, project_type, reserved_codes)
                reserved_codes.add(project_code)
                status = _pick_value(raw_row, FIELD_ALIASES["current_status"])
                status = STATUS_CN_TO_EN.get(status, status.lower()) or "draft"
                if status not in VALID_STATUS_CODES:
                    status = "draft"
                budget_value = _pick_value(raw_row, FIELD_ALIASES["budget"])
                approved_value = _pick_value(raw_row, FIELD_ALIASES["approved_budget"])
                contract_value = _pick_value(raw_row, FIELD_ALIASES["contract_amount"])
                record = ImportPreviewRecord(
                    row_number=index,
                    project_code=project_code,
                    name=name,
                    description=_pick_value(raw_row, FIELD_ALIASES["description"]),
                    department=_pick_value(raw_row, FIELD_ALIASES["department"]),
                    sponsor=_pick_value(raw_row, FIELD_ALIASES["sponsor"]),
                    project_manager=_pick_value(raw_row, FIELD_ALIASES["project_manager"]),
                    current_status=status,
                    category=_pick_value(raw_row, FIELD_ALIASES["category"]),
                    project_type=project_type,
                    budget=float(budget_value or 0),
                    approved_budget=float(approved_value) if approved_value else None,
                    contract_amount=float(contract_value) if contract_value else None,
                    special_note=_pick_value(raw_row, FIELD_ALIASES["special_note"]),
                    actual_start_date=_pick_value(raw_row, FIELD_ALIASES["actual_start_date"]),
                    actual_end_date=_pick_value(raw_row, FIELD_ALIASES["actual_end_date"]),
                )
                records.append(record)
            except Exception as exc:
                errors.append(
                    ImportPreviewErrorItem(
                        row_number=index,
                        code=getattr(exc, "code", "IMPORT_PREVIEW_ERROR"),
                        message=str(exc),
                        name=_pick_value(raw_row, FIELD_ALIASES["name"]) or None,
                    )
                )
    return {
        "total_rows": len(df.index),
        "valid_rows": len(records),
        "invalid_rows": len(errors),
        "records": records,
        "errors": errors,
    }


def commit_import(records: list[ImportPreviewRecord], operator: str) -> dict:
    result = {"total": len(records), "success": 0, "failed": 0, "errors": []}
    for record in records:
        try:
            create_project_internal(
                {
                    **record.model_dump(),
                    "operator": operator,
                    "approved_budget": record.approved_budget,
                }
            )
            result["success"] += 1
        except Exception as exc:
            result["failed"] += 1
            result["errors"].append(
                {
                    "row_number": record.row_number,
                    "name": record.name,
                    "code": getattr(exc, "code", "IMPORT_COMMIT_ERROR"),
                    "message": str(exc),
                }
            )
    return result
