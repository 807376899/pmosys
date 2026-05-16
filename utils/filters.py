from __future__ import annotations

from utils.constants import GROUP_FILTERS, GROUP_ORDER
from utils.formatters import get_status_name, get_status_order_map


def _extract_year(value: str | None) -> str | None:
    """从日期或编号文本中提取年份。"""
    if not value:
        return None
    cleaned = str(value).strip()
    if len(cleaned) >= 4 and cleaned[:4].isdigit():
        return cleaned[:4]
    return None


def get_declaration_year(project: dict) -> str | None:
    """获取项目申报年份，优先取项目编号中的年份。"""
    project_code = str(project.get("project_code") or "").strip()
    parts = project_code.split("-")
    if len(parts) >= 3 and parts[1].isdigit():
        return parts[1]
    return _extract_year(project.get("created_at"))


def get_implementation_year(project: dict) -> str | None:
    """获取项目实施年份。"""
    return _extract_year(project.get("actual_start_date"))


def filter_projects_by_group(projects: list[dict], group_key: str) -> list[dict]:
    """按统筹视角过滤项目。"""
    group = GROUP_FILTERS.get(group_key, GROUP_FILTERS["all"])
    statuses = group["statuses"]
    if not statuses:
        return projects
    allowed = set(statuses)
    return [project for project in projects if project["current_status"] in allowed]


def apply_dashboard_filters(
    projects: list[dict],
    *,
    detail_status_name: str,
    declaration_year: str,
    implementation_year: str,
) -> list[dict]:
    """应用工作台轻量筛选。"""
    filtered = projects

    if detail_status_name != "全部":
        filtered = [
            project for project in filtered if get_status_name(project["current_status"]) == detail_status_name
        ]

    if declaration_year != "全部":
        filtered = [
            project for project in filtered if get_declaration_year(project) == declaration_year
        ]

    if implementation_year != "全部":
        filtered = [
            project for project in filtered if get_implementation_year(project) == implementation_year
        ]

    return filtered


def get_year_options(projects: list[dict], extractor) -> list[str]:
    """获取年份下拉选项。"""
    years = {extractor(project) for project in projects}
    valid_years = [year for year in years if year]
    return sorted(valid_years, reverse=True)


def build_group_counts(projects: list[dict]) -> dict[str, int]:
    """统计各统筹视角下的项目数量。"""
    counts = {group_key: 0 for group_key in GROUP_ORDER}
    counts["all"] = len(projects)
    for group_key in GROUP_ORDER:
        if group_key == "all":
            continue
        counts[group_key] = len(filter_projects_by_group(projects, group_key))
    return counts


def build_group_summary(projects: list[dict]) -> str:
    """构建状态摘要。"""
    counter: dict[str, int] = {}
    for project in projects:
        counter[project["current_status"]] = counter.get(project["current_status"], 0) + 1

    return "，".join(
        get_status_name(status_code) + " " + str(count) + " 个"
        for status_code, count in sorted(
            counter.items(),
            key=lambda item: get_status_order_map().get(item[0], 999),
        )
    )
