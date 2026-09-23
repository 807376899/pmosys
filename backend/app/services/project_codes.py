from __future__ import annotations

from datetime import datetime
import re

from backend.app.core.errors import DuplicateProjectCodeError, ValidationError
from backend.app.repositories import projects as project_repo
ALIASES = {"teaching_software": "SW", "software": "SW", "practical_teaching_site": "SY", "laboratory": "SY"}


def project_type_prefix(conn, project_type: str) -> str:
    row = conn.execute("SELECT code_prefix FROM project_types WHERE code = ? AND is_active = 1", (project_type,)).fetchone()
    if row:
        return row[0]
    if project_type in ALIASES:
        return ALIASES[project_type]
    raise ValidationError(f"项目类型不存在或已停用: {project_type}")


def validate_manual_project_code(conn, project_code: str, project_type: str, *, allow_historical_year: bool = False) -> str:
    project_code = project_code.strip().upper()
    prefix = project_type_prefix(conn, project_type)
    match = re.fullmatch(rf"{re.escape(prefix)}(\d{{4}})\d{{4}}", project_code)
    if not match:
        raise ValidationError(
            f"项目编号须为 {prefix} 加四位年份和四位流水号，例如 {prefix}{datetime.now().year}0001",
            code="VALIDATION_ERROR",
        )
    year = int(match.group(1))
    current_year = datetime.now().year
    if allow_historical_year:
        if not 1900 <= year <= current_year:
            raise ValidationError(f"历史导入项目编号年份须在 1900 至 {current_year} 之间", code="VALIDATION_ERROR")
    elif year != current_year:
        raise ValidationError(
            f"项目编号须为 {prefix}{current_year} 加四位流水号，例如 {prefix}{current_year}0001",
            code="VALIDATION_ERROR",
        )
    return project_code


def generate_project_code(conn, project_type: str) -> str:
    year = datetime.now().year
    prefix = project_type_prefix(conn, project_type)
    max_code = project_repo.fetch_max_project_code(conn, prefix, year)
    if max_code:
        seq = int(max_code[-4:]) + 1
    else:
        seq = 1
    for _ in range(9999):
        candidate = f"{prefix}{year}{seq:04d}"
        if not project_repo.project_code_exists(conn, candidate):
            return candidate
        seq += 1
    raise DuplicateProjectCodeError("项目编号生成失败，请稍后重试")
