from __future__ import annotations

from datetime import datetime

from backend.app.core.errors import DuplicateProjectCodeError, ValidationError
from backend.app.repositories import projects as project_repo
from backend.app.schemas.project import PROJECT_TYPE_META, ProjectType


def project_type_prefix(project_type: ProjectType) -> str:
    return PROJECT_TYPE_META[project_type]["prefix"]


def validate_manual_project_code(project_code: str, project_type: ProjectType) -> str:
    project_code = project_code.strip().upper()
    prefix = project_type_prefix(project_type)
    if not project_code.startswith(prefix):
        raise ValidationError(
            f"项目编号 {project_code} 与项目类型不匹配",
            code="VALIDATION_ERROR",
        )
    return project_code


def generate_project_code(conn, project_type: ProjectType) -> str:
    year = datetime.now().year
    prefix = project_type_prefix(project_type)
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

