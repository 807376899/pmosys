from __future__ import annotations

from fastapi import Query


def project_filters(
    status: str | None = None,
    group: str | None = None,
    keyword: str | None = None,
    department: str | None = None,
    project_manager: str | None = None,
    project_type: str | None = None,
    category: str | None = None,
    min_budget: float | None = None,
    max_budget: float | None = None,
    declaration_year: str | None = None,
    implementation_year: str | None = None,
    status_updated_from: str | None = None,
    status_updated_to: str | None = None,
    sort_by: str | None = None,
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> dict:
    return {
        "status": status,
        "group": group,
        "keyword": keyword,
        "department": department,
        "project_manager": project_manager,
        "project_type": project_type,
        "category": category,
        "min_budget": min_budget,
        "max_budget": max_budget,
        "declaration_year": declaration_year,
        "implementation_year": implementation_year,
        "status_updated_from": status_updated_from,
        "status_updated_to": status_updated_to,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "page": page,
        "page_size": page_size,
    }
