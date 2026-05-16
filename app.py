"""
PMO项目管理系统 - Streamlit 主应用

Phase 3.1 重点：
1. 修复批量勾选不稳定的问题
2. 增加送审审核后预算 approved_budget
3. 强化 PMO 统筹视角、批量确认与失败清单导出
"""

from __future__ import annotations

import hashlib
import io
from datetime import date, datetime
from typing import Optional

import pandas as pd
import streamlit as st

from lib.database import (
    VALID_STATUS_CODES,
    batch_create_projects,
    batch_transition_projects,
    create_project,
    generate_mermaid_diagram,
    generate_project_code,
    get_all_statuses,
    get_all_transition_rules,
    get_allowed_transitions,
    get_departments,
    get_project_by_id,
    get_project_managers,
    get_projects,
    get_status_history,
    init_database,
    transition_allows_budget_adjustment,
    transition_project,
    update_project,
)


st.set_page_config(
    page_title="PMO项目管理系统",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_database()


GROUP_FILTERS = {
    "all": {"label": "全部项目", "statuses": None},
    "pre_establish": {"label": "未立项", "statuses": ["draft", "under_review"]},
    "pool_pending": {"label": "项目库-未实施", "statuses": ["established", "submission_review"]},
    "pool_active": {
        "label": "项目库-实施中",
        "statuses": ["procuring", "implementing", "trial", "accepting", "suspended"],
    },
    "completed": {"label": "已完成", "statuses": ["closed"]},
    "abandoned": {"label": "已废弃", "statuses": ["terminated"]},
}


@st.cache_data(ttl=30)
def _get_status_definitions() -> list[dict]:
    """缓存状态定义"""
    return get_all_statuses()


def _get_status_map() -> dict[str, str]:
    """状态码 -> 中文名"""
    return {item["status_code"]: item["status_name"] for item in _get_status_definitions()}


def _get_status_order_map() -> dict[str, int]:
    """状态码 -> 排序号"""
    return {item["status_code"]: item["sort_order"] for item in _get_status_definitions()}


def _get_status_color(status_code: str) -> str:
    """获取状态颜色"""
    for item in _get_status_definitions():
        if item["status_code"] == status_code:
            return item["color"]
    return "#6B7280"


def _get_status_name(status_code: str) -> str:
    """获取状态中文名"""
    return _get_status_map().get(status_code, status_code)


def _current_operator() -> str:
    """获取当前操作人"""
    return st.session_state.current_user.strip() or "PMO办公室"


def _is_pmo_mode() -> bool:
    """是否为 PMO 模式"""
    return st.session_state.current_role == "PMO"


def _normalize_date_start(value: Optional[date]) -> Optional[str]:
    """日期开始边界"""
    if not value:
        return None
    return value.strftime("%Y-%m-%d 00:00:00")


def _normalize_date_end(value: Optional[date]) -> Optional[str]:
    """日期结束边界"""
    if not value:
        return None
    return value.strftime("%Y-%m-%d 23:59:59")


def init_session_state() -> None:
    """初始化会话状态"""
    defaults = {
        "view": "dashboard",
        "selected_project_id": None,
        "refresh_counter": 0,
        "current_user": "PMO办公室",
        "current_role": "PMO",
        "dashboard_group_filter": "all",
        "dashboard_status_code": None,
        "selected_project_ids": [],
        "editing_project": False,
        "batch_feedback": None,
        "pending_batch_payload": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


def go_dashboard() -> None:
    """跳转工作台"""
    st.session_state.view = "dashboard"
    st.session_state.selected_project_id = None
    st.rerun()


def go_create() -> None:
    """跳转新增项目"""
    st.session_state.view = "create"
    st.rerun()


def go_detail(project_id: int) -> None:
    """跳转项目详情"""
    st.session_state.view = "detail"
    st.session_state.selected_project_id = project_id
    st.session_state.editing_project = False
    st.rerun()


def go_import() -> None:
    """跳转批量导入"""
    st.session_state.view = "import"
    st.rerun()


def go_workflow() -> None:
    """跳转工作流管理"""
    st.session_state.view = "workflow"
    st.rerun()


def _clear_selection() -> None:
    """清空选中项目"""
    st.session_state.selected_project_ids = []


def _status_badge(status_code: str) -> str:
    """状态徽章"""
    style = (
        "display:inline-block; padding:3px 10px; border-radius:999px; "
        "color:white; font-size:12px; font-weight:600; "
        "background-color:" + _get_status_color(status_code) + ";"
    )
    return '<span style="' + style + '">' + _get_status_name(status_code) + "</span>"


def _budget_display(value: Optional[float]) -> str:
    """预算展示文本"""
    if value is None:
        return "-"
    return f"{float(value):,.2f}"


def _filter_projects_by_group(projects: list[dict], group_key: str) -> list[dict]:
    """按四大视角分类过滤项目"""
    group = GROUP_FILTERS.get(group_key, GROUP_FILTERS["all"])
    statuses = group["statuses"]
    if not statuses:
        return projects
    allowed = set(statuses)
    return [project for project in projects if project["current_status"] in allowed]


def _filter_projects_by_status(projects: list[dict], status_code: Optional[str]) -> list[dict]:
    """按状态卡片过滤项目"""
    if not status_code:
        return projects
    return [project for project in projects if project["current_status"] == status_code]


def _build_status_stats(projects: list[dict]) -> list[dict]:
    """根据当前筛选结果构建状态统计"""
    counts: dict[str, int] = {}
    for project in projects:
        counts[project["current_status"]] = counts.get(project["current_status"], 0) + 1

    rows = []
    for status in _get_status_definitions():
        rows.append(
            {
                "status_code": status["status_code"],
                "status_name": status["status_name"],
                "color": status["color"],
                "project_count": counts.get(status["status_code"], 0),
            }
        )
    return rows


def _build_export_bytes(projects: list[dict]) -> bytes:
    """导出项目 Excel"""
    export_rows = []
    for project in projects:
        export_rows.append(
            {
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "当前状态": _get_status_name(project["current_status"]),
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


def _build_batch_failure_export_bytes(errors: list[dict]) -> bytes:
    """导出批量失败清单"""
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


def _build_selection_editor_key(projects: list[dict]) -> str:
    """基于当前结果集生成稳定编辑器 key"""
    raw = "|".join(str(project["id"]) for project in projects)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]
    return "dashboard_project_editor_" + digest


def _build_common_transition_options(projects: list[dict]) -> list[dict]:
    """计算一组项目的共同合法下一状态"""
    if not projects:
        return []

    unique_statuses = sorted({project["current_status"] for project in projects})
    transition_maps: list[dict[str, dict]] = []

    for status_code in unique_statuses:
        options = {}
        for item in get_allowed_transitions(status_code):
            options[item["to_status"]] = {
                "to_status": item["to_status"],
                "status_name": item.get("to_status_name") or _get_status_name(item["to_status"]),
                "requires_approval": bool(item["requires_approval"]),
                "approver_roles": {item.get("approver_role") or ""},
                "action_names": {item["action_name"]},
            }
        transition_maps.append(options)

    common_targets = set(transition_maps[0].keys())
    for transition_map in transition_maps[1:]:
        common_targets &= set(transition_map.keys())

    merged = []
    for to_status in common_targets:
        requires_approval = False
        approver_roles: set[str] = set()
        action_names: set[str] = set()
        for transition_map in transition_maps:
            option = transition_map[to_status]
            requires_approval = requires_approval or option["requires_approval"]
            approver_roles |= option["approver_roles"]
            action_names |= option["action_names"]

        merged.append(
            {
                "to_status": to_status,
                "status_name": _get_status_name(to_status),
                "requires_approval": requires_approval,
                "approver_roles": sorted(role for role in approver_roles if role),
                "action_names": sorted(action_names),
            }
        )

    merged.sort(key=lambda item: _get_status_order_map().get(item["to_status"], 999))
    return merged


def _build_force_transition_options(projects: list[dict]) -> list[dict]:
    """构建 PMO 特批可选状态"""
    options = []
    for status in _get_status_definitions():
        count = sum(1 for project in projects if project["current_status"] == status["status_code"])
        hint = f"（当前 {count} 个）" if count else ""
        options.append(
            {
                "to_status": status["status_code"],
                "status_name": status["status_name"] + hint,
                "requires_approval": True,
                "approver_roles": ["PMO"],
                "action_names": ["PMO特批强制变更"],
            }
        )
    return options


def _batch_budget_adjustment_allowed(projects: list[dict], to_status: str) -> bool:
    """批量场景是否允许调整审核后预算"""
    return any(
        transition_allows_budget_adjustment(project["current_status"], to_status)
        for project in projects
    )


def _build_group_summary(projects: list[dict]) -> str:
    """构建状态摘要"""
    counter: dict[str, int] = {}
    for project in projects:
        counter[project["current_status"]] = counter.get(project["current_status"], 0) + 1
    return "，".join(
        _get_status_name(status_code) + " " + str(count) + " 个"
        for status_code, count in sorted(
            counter.items(),
            key=lambda item: _get_status_order_map().get(item[0], 999),
        )
    )


def _generate_import_template() -> bytes:
    """生成导入模板"""
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
        status_rows.append({"状态码": status_code, "中文名": _get_status_name(status_code)})
    status_rows.sort(key=lambda item: _get_status_order_map().get(item["状态码"], 999))

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(instructions_data).to_excel(writer, index=False, sheet_name="字段说明")
        pd.DataFrame(status_rows).to_excel(writer, index=False, sheet_name="合法状态列表")
        pd.DataFrame(template_data).to_excel(writer, index=False, sheet_name="导入模板(请复制此sheet)")
    output.seek(0)
    return output.getvalue()


@st.dialog("确认批量操作")
def _render_batch_confirmation_dialog() -> None:
    """批量操作确认弹窗"""
    payload = st.session_state.pending_batch_payload
    if not payload:
        return

    projects = payload["projects"]
    from_summary = _build_group_summary(projects)
    st.markdown(
        "本次将把 **"
        + str(len(projects))
        + "** 个项目，从 **"
        + from_summary
        + "** 推进到 **"
        + payload["target_status_name"]
        + "**。"
    )

    if payload["force_mode"]:
        st.warning("当前为 PMO 特批强制变更，将跳过常规流转规则校验。")

    if payload["approved_budget"] is not None:
        st.info("本次将统一写入审核后预算：" + _budget_display(payload["approved_budget"]) + " 万元。")

    affected_rows = []
    for project in projects:
        affected_rows.append(
            {
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "当前状态": _get_status_name(project["current_status"]),
                "初始申报预算(万元)": float(project.get("budget") or 0),
                "审核后预算(万元)": project.get("approved_budget"),
            }
        )
    st.dataframe(pd.DataFrame(affected_rows), use_container_width=True, hide_index=True)

    confirm_col1, confirm_col2 = st.columns(2)
    with confirm_col1:
        if st.button("确认执行", type="primary", use_container_width=True):
            result = batch_transition_projects(
                project_ids=[project["id"] for project in projects],
                to_status=payload["target_status"],
                operator=payload["operator"],
                approver=payload["approver"],
                comment=payload["comment"],
                deliverable=payload["deliverable"],
                force=payload["force_mode"],
                approved_budget=payload["approved_budget"],
            )
            st.session_state.batch_feedback = result
            st.session_state.pending_batch_payload = None
            _clear_selection()
            st.rerun()
    with confirm_col2:
        if st.button("取消", use_container_width=True):
            st.session_state.pending_batch_payload = None
            st.rerun()


def _render_group_filter_buttons() -> None:
    """渲染四大统筹视角"""
    st.markdown("### 四大统筹视角")
    st.caption("项目库视角拆分为“未实施”和“实施中”，便于 PMO 快速统筹。")

    button_cols = st.columns(6)
    ordered_keys = ["all", "pre_establish", "pool_pending", "pool_active", "completed", "abandoned"]
    for col, key in zip(button_cols, ordered_keys):
        with col:
            is_active = st.session_state.dashboard_group_filter == key
            label = GROUP_FILTERS[key]["label"]
            if is_active:
                label = "✓ " + label
            if st.button(label, key="group_filter_" + key, use_container_width=True):
                st.session_state.dashboard_group_filter = key
                st.session_state.dashboard_status_code = None
                _clear_selection()
                st.rerun()


def _render_status_cards(stats: list[dict]) -> None:
    """渲染状态分布卡片"""
    current_filter = st.session_state.dashboard_status_code
    st.markdown("### 状态分布")

    action_col1, action_col2 = st.columns([1, 5])
    with action_col1:
        if st.button("清除状态过滤", use_container_width=True):
            st.session_state.dashboard_status_code = None
            _clear_selection()
            st.rerun()
    with action_col2:
        label = _get_status_name(current_filter) if current_filter else "全部状态"
        st.caption("当前状态过滤：" + label)

    chunk_size = 4
    for start in range(0, len(stats), chunk_size):
        chunk = stats[start : start + chunk_size]
        columns = st.columns(chunk_size)
        for col, stat in zip(columns, chunk):
            active = current_filter == stat["status_code"]
            with col:
                color = stat["color"]
                background = "#eff6ff" if active else "#f8fafc"
                st.markdown(
                    '<div style="padding:12px; border-radius:12px; border:1px solid '
                    + color
                    + "; background:"
                    + background
                    + ';">'
                    + '<div style="font-size:13px; color:#475569;">'
                    + stat["status_name"]
                    + "</div>"
                    + '<div style="font-size:28px; font-weight:700; color:'
                    + color
                    + ';">'
                    + str(stat["project_count"])
                    + "</div>"
                    + "</div>",
                    unsafe_allow_html=True,
                )
                btn_label = "已筛选" if active else "筛选此状态"
                if st.button(btn_label, key="status_card_" + stat["status_code"], use_container_width=True):
                    st.session_state.dashboard_status_code = stat["status_code"]
                    _clear_selection()
                    st.rerun()


def _render_budget_adjustment_inputs(
    *,
    key_prefix: str,
    current_budget: float,
    current_approved_budget: Optional[float],
    enabled: bool,
) -> tuple[bool, Optional[float]]:
    """渲染审核后预算调整输入"""
    if not enabled:
        return False, None

    default_value = float(
        current_approved_budget if current_approved_budget is not None else current_budget
    )
    adjust_budget = st.checkbox(
        "本次同步调整审核后预算",
        key=key_prefix + "_adjust_approved_budget",
        help="仅在进入送审中或从送审中流转时允许填写。",
    )
    approved_budget = None
    if adjust_budget:
        approved_budget = st.number_input(
            "审核后预算（万元）",
            min_value=0.0,
            value=default_value,
            step=10.0,
            key=key_prefix + "_approved_budget",
        )
    return adjust_budget, approved_budget


def render_dashboard() -> None:
    """渲染 PMO 统筹工作台"""
    st.markdown("## PMO统筹工作台")
    st.caption("围绕四大分类、状态分布和批量推进，帮助 PMO 高效完成项目统筹。")

    toolbar_cols = st.columns([1, 1, 1, 1, 1])
    with toolbar_cols[0]:
        if st.button("➕ 新增项目", use_container_width=True):
            go_create()
    with toolbar_cols[1]:
        if st.button("📥 批量导入", use_container_width=True):
            go_import()
    with toolbar_cols[2]:
        if st.button("🔄 工作流管理", use_container_width=True):
            go_workflow()
    with toolbar_cols[3]:
        if st.button("♻️ 刷新页面", use_container_width=True):
            st.session_state.refresh_counter += 1
            st.rerun()
    with toolbar_cols[4]:
        st.caption("默认按状态更新时间倒序展示")

    if st.session_state.batch_feedback:
        feedback = st.session_state.batch_feedback
        result_col1, result_col2, result_col3 = st.columns(3)
        with result_col1:
            st.metric("本次处理总数", feedback["total"])
        with result_col2:
            st.metric("成功", feedback["success"])
        with result_col3:
            st.metric("失败", feedback["failed"])

        if feedback["failed"] == 0:
            st.success("批量操作已完成。")
        else:
            st.warning("批量操作已完成，但存在失败项目。")
            failure_bytes = _build_batch_failure_export_bytes(feedback["errors"])
            download_col1, download_col2 = st.columns([1, 4])
            with download_col1:
                st.download_button(
                    "下载失败清单",
                    data=failure_bytes,
                    file_name="批量操作失败清单_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            with download_col2:
                with st.expander("查看失败详情"):
                    for item in feedback["errors"]:
                        st.error(
                            item["project_code"]
                            + " | "
                            + item["name"]
                            + "："
                            + item["error"]
                        )

    st.markdown("---")
    _render_group_filter_buttons()

    st.markdown("---")
    st.markdown("### 筛选条件")
    with st.expander("展开高级筛选", expanded=False):
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        with filter_col1:
            departments = get_departments()
            department = st.selectbox(
                "申报部门",
                options=["全部"] + departments,
                key="dashboard_department",
            )
        with filter_col2:
            managers = get_project_managers()
            manager = st.selectbox(
                "项目负责人",
                options=["全部"] + managers,
                key="dashboard_manager",
            )
        with filter_col3:
            min_budget = st.number_input(
                "最低申报预算（万元）",
                min_value=0.0,
                value=0.0,
                step=10.0,
                key="dashboard_min_budget",
            )
        with filter_col4:
            max_budget = st.number_input(
                "最高申报预算（万元）",
                min_value=0.0,
                value=0.0,
                step=10.0,
                key="dashboard_max_budget",
            )

        date_col1, date_col2 = st.columns(2)
        with date_col1:
            status_updated_from = st.date_input(
                "状态更新开始日期",
                value=None,
                key="dashboard_status_from",
            )
        with date_col2:
            status_updated_to = st.date_input(
                "状态更新结束日期",
                value=None,
                key="dashboard_status_to",
            )

        keyword = st.text_input(
            "关键词搜索",
            placeholder="支持项目编号 / 名称 / 描述 / 发起人 / 特殊说明",
            key="dashboard_keyword",
        )

    query_department = None if department == "全部" else department
    query_manager = None if manager == "全部" else manager
    query_min_budget = min_budget if min_budget > 0 else None
    query_max_budget = max_budget if max_budget > 0 else None

    if query_min_budget is not None and query_max_budget is not None and query_min_budget > query_max_budget:
        st.error("预算范围无效：最低预算不能大于最高预算。")
        return

    base_projects = get_projects(
        keyword=keyword.strip() or None,
        department=query_department,
        project_manager=query_manager,
        min_budget=query_min_budget,
        max_budget=query_max_budget,
        status_updated_from=_normalize_date_start(status_updated_from),
        status_updated_to=_normalize_date_end(status_updated_to),
    )
    base_projects = _filter_projects_by_group(base_projects, st.session_state.dashboard_group_filter)

    stats = _build_status_stats(base_projects)

    _render_status_cards(stats)

    visible_projects = _filter_projects_by_status(base_projects, st.session_state.dashboard_status_code)
    visible_ids = {project["id"] for project in visible_projects}
    st.session_state.selected_project_ids = [
        project_id
        for project_id in st.session_state.selected_project_ids
        if project_id in visible_ids
    ]

    st.markdown("---")
    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    with summary_col1:
        st.metric("当前结果数", len(visible_projects))
    with summary_col2:
        st.metric("已选中", len(st.session_state.selected_project_ids))
    with summary_col3:
        st.metric(
            "初始申报预算合计（万元）",
            f"{sum(float(project.get('budget') or 0) for project in visible_projects):,.1f}",
        )
    with summary_col4:
        approved_budget_sum = sum(
            float(project["approved_budget"])
            for project in visible_projects
            if project.get("approved_budget") is not None
        )
        st.metric("审核后预算合计（万元）", f"{approved_budget_sum:,.1f}")

    if not visible_projects:
        st.info("当前筛选条件下暂无项目。")
        return

    export_bytes = _build_export_bytes(visible_projects)
    export_col1, export_col2, export_col3 = st.columns([1, 1, 4])
    with export_col1:
        st.download_button(
            "导出当前结果",
            data=export_bytes,
            file_name="PMO筛选结果_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with export_col2:
        if st.button("清空勾选", use_container_width=True):
            _clear_selection()
            st.rerun()
    with export_col3:
        detail_options = {
            project["project_code"] + " | " + project["name"]: project["id"]
            for project in visible_projects
        }
        quick_label = st.selectbox("快速查看项目详情", options=list(detail_options.keys()))
        if st.button("查看详情", use_container_width=True):
            go_detail(detail_options[quick_label])

    action_col1, action_col2 = st.columns([1, 1])
    with action_col1:
        if st.button("全选当前结果", use_container_width=True):
            st.session_state.selected_project_ids = [project["id"] for project in visible_projects]
            st.rerun()
    with action_col2:
        st.caption("勾选表格行后，点击“更新勾选结果”即可进入批量操作。")

    table_rows = []
    for project in visible_projects:
        table_rows.append(
            {
                "选择": project["id"] in st.session_state.selected_project_ids,
                "project_id": project["id"],
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "当前状态": _get_status_name(project["current_status"]),
                "申报部门": project.get("department") or "",
                "项目负责人": project.get("project_manager") or "",
                "初始申报预算(万元)": float(project.get("budget") or 0),
                "审核后预算(万元)": project.get("approved_budget"),
                "状态更新时间": project.get("status_updated_at") or "",
                "特殊说明": project.get("special_note") or "",
            }
        )

    editor_key = _build_selection_editor_key(visible_projects)
    with st.form("dashboard_selection_form", clear_on_submit=False):
        edited_df = st.data_editor(
            pd.DataFrame(table_rows),
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            height=520,
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", help="勾选后用于批量操作"),
                "project_id": None,
                "初始申报预算(万元)": st.column_config.NumberColumn("初始申报预算(万元)", format="%.2f"),
                "审核后预算(万元)": st.column_config.NumberColumn("审核后预算(万元)", format="%.2f"),
                "特殊说明": st.column_config.TextColumn("特殊说明", width="large"),
            },
            disabled=[
                "project_id",
                "项目编号",
                "项目名称",
                "当前状态",
                "申报部门",
                "项目负责人",
                "初始申报预算(万元)",
                "审核后预算(万元)",
                "状态更新时间",
                "特殊说明",
            ],
            key=editor_key,
        )
        selection_submitted = st.form_submit_button("更新勾选结果", use_container_width=True)

    if selection_submitted:
        selected_ids = edited_df.loc[edited_df["选择"], "project_id"].tolist()
        st.session_state.selected_project_ids = [int(item) for item in selected_ids]

    selected_projects = [
        project for project in visible_projects if project["id"] in st.session_state.selected_project_ids
    ]
    if not selected_projects:
        st.info("先在上方项目列表中勾选项目，再点击“更新勾选结果”，即可进行批量推进。")
        if st.session_state.pending_batch_payload:
            _render_batch_confirmation_dialog()
        return

    st.markdown("---")
    st.markdown("### 批量操作")
    st.caption("当前已选中 " + str(len(selected_projects)) + " 个项目：" + _build_group_summary(selected_projects))

    force_mode = False
    if _is_pmo_mode():
        force_mode = st.checkbox(
            "启用 PMO 特批强制变更（跳过常规流转校验）",
            key="dashboard_force_mode",
        )

    if force_mode:
        option_items = _build_force_transition_options(selected_projects)
        st.warning("当前为 PMO 特批模式，系统会记录“PMO特批强制变更”历史。")
    else:
        option_items = _build_common_transition_options(selected_projects)

    if not option_items:
        st.warning("这批项目没有共同的合法下一状态。请缩小选择范围，或切换到 PMO 特批模式。")
        if st.session_state.pending_batch_payload:
            _render_batch_confirmation_dialog()
        return

    option_map = {}
    option_labels = []
    for item in option_items:
        approval_tag = " [需审批]" if item["requires_approval"] else ""
        action_tag = " / ".join(item["action_names"])
        label = item["status_name"] + approval_tag + " — " + action_tag
        option_labels.append(label)
        option_map[label] = item

    batch_col1, batch_col2 = st.columns(2)
    with batch_col1:
        selected_label = st.selectbox(
            "目标状态",
            options=option_labels,
            key="dashboard_batch_target",
        )
        operator = st.text_input(
            "操作人",
            value=_current_operator(),
            key="dashboard_batch_operator",
        )
        deliverable = st.text_input(
            "交付物",
            key="dashboard_batch_deliverable",
            placeholder="可选，例如：立项批复 / 采购申请 / 验收报告",
        )
    with batch_col2:
        default_approver = _current_operator() if (_is_pmo_mode() or force_mode) else ""
        approver = st.text_input(
            "审批人",
            value=default_approver,
            key="dashboard_batch_approver",
            help="常规流转在规则要求审批时必填；PMO 特批建议默认填写当前操作人。",
        )
        comment = st.text_area(
            "批量变更理由",
            key="dashboard_batch_comment",
            height=112,
            placeholder="请填写统一推进理由，例如：本周评审会已集中通过，批量推进至已立项。",
        )

    selected_option = option_map[selected_label]
    if selected_option["requires_approval"]:
        role_text = "、".join(selected_option["approver_roles"]) if selected_option["approver_roles"] else "指定审批人"
        st.info("当前目标状态涉及审批要求，建议审批人填写：" + role_text)

    budget_adjustment_allowed = _batch_budget_adjustment_allowed(selected_projects, selected_option["to_status"])
    adjust_budget, approved_budget = _render_budget_adjustment_inputs(
        key_prefix="dashboard_batch",
        current_budget=float(selected_projects[0].get("budget") or 0),
        current_approved_budget=selected_projects[0].get("approved_budget"),
        enabled=budget_adjustment_allowed,
    )
    if budget_adjustment_allowed:
        st.caption("送审预算逻辑：初始申报预算保持不变，本次如填写则统一更新“审核后预算”。")

    if st.button("进入二次确认", type="primary", use_container_width=True):
        errors = []
        if not operator.strip():
            errors.append("操作人不能为空。")
        if not comment.strip():
            errors.append("批量变更理由不能为空。")
        if (force_mode or selected_option["requires_approval"]) and not approver.strip():
            errors.append("当前操作需要审批人，请填写审批人。")
        if adjust_budget and approved_budget is None:
            errors.append("请填写审核后预算。")

        if errors:
            for error in errors:
                st.error(error)
        else:
            st.session_state.pending_batch_payload = {
                "projects": selected_projects,
                "target_status": selected_option["to_status"],
                "target_status_name": _get_status_name(selected_option["to_status"]),
                "operator": operator.strip(),
                "approver": approver.strip() or None,
                "comment": comment.strip(),
                "deliverable": deliverable.strip(),
                "force_mode": force_mode,
                "approved_budget": approved_budget if adjust_budget else None,
            }
            st.rerun()

    if st.session_state.pending_batch_payload:
        _render_batch_confirmation_dialog()


def render_create_project() -> None:
    """渲染新增项目页面"""
    st.markdown("## ➕ 新增项目")
    st.caption("项目创建后默认为“草稿”状态，编号由系统自动生成。")

    with st.form("create_project_form"):
        auto_code = generate_project_code()
        st.text_input("项目编号（自动生成）", value=auto_code, disabled=True)
        name = st.text_input("项目名称 *", placeholder="请输入项目名称")

        col1, col2 = st.columns(2)
        with col1:
            department = st.text_input("申报部门", placeholder="如：信息中心")
        with col2:
            project_manager = st.text_input("项目负责人", placeholder="如：张工")

        col3, col4 = st.columns(2)
        with col3:
            sponsor = st.text_input("发起人", placeholder="如：王主任")
        with col4:
            category = st.text_input("项目分类", placeholder="如：信息化建设")

        col5, col6 = st.columns(2)
        with col5:
            budget = st.number_input("初始申报预算（万元）", min_value=0.0, value=0.0, step=10.0)
        with col6:
            operator = st.text_input("操作人 *", value=_current_operator())

        description = st.text_area("项目描述", height=100, placeholder="请简要描述项目内容")
        special_note = st.text_area("特殊说明", height=80, placeholder="记录政策变化、直采说明、跳过送审依据等")

        submit_col1, submit_col2 = st.columns(2)
        with submit_col1:
            submitted = st.form_submit_button("✅ 创建项目", use_container_width=True)
        with submit_col2:
            cancelled = st.form_submit_button("← 返回工作台", use_container_width=True)

        if cancelled:
            go_dashboard()

        if submitted:
            if not name.strip():
                st.error("项目名称不能为空。")
            elif not operator.strip():
                st.error("操作人不能为空。")
            else:
                new_id = create_project(
                    name=name.strip(),
                    project_code=auto_code,
                    description=description.strip(),
                    department=department.strip(),
                    sponsor=sponsor.strip(),
                    project_manager=project_manager.strip(),
                    category=category.strip(),
                    budget=budget,
                    special_note=special_note.strip(),
                    operator=operator.strip(),
                )
                st.success("项目创建成功，编号：" + auto_code)
                go_detail(new_id)


def _render_project_info(project: dict) -> None:
    """渲染项目基本信息"""
    if st.session_state.editing_project:
        _render_edit_form(project)
    else:
        _render_info_display(project)


def _render_info_display(project: dict) -> None:
    """只读展示项目信息"""
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**项目编号：** " + project["project_code"])
        st.markdown("**项目名称：** " + project["name"])
        st.markdown("**申报部门：** " + (project.get("department") or "-"))
        st.markdown("**项目负责人：** " + (project.get("project_manager") or "-"))
        st.markdown("**发起人：** " + (project.get("sponsor") or "-"))
    with col2:
        st.markdown("**当前状态：** " + _get_status_name(project["current_status"]))
        st.markdown("**项目分类：** " + (project.get("category") or "-"))
        st.markdown("**初始申报预算：** " + _budget_display(project.get("budget")) + " 万元")
        st.markdown("**审核后预算：** " + _budget_display(project.get("approved_budget")) + " 万元")
        st.markdown("**状态更新时间：** " + (project.get("status_updated_at") or "-"))
        st.markdown("**实际开始日期：** " + (project.get("actual_start_date") or "-"))
        st.markdown("**实际结束日期：** " + (project.get("actual_end_date") or "-"))

    st.markdown("**项目描述：**")
    st.markdown(project.get("description") or "（暂无描述）")

    st.markdown("**特殊说明：**")
    note = project.get("special_note") or "（暂无特殊说明）"
    st.markdown(
        '<div style="padding:12px; border-radius:10px; background:#fff7ed; border:1px solid #fdba74;">'
        + note
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.caption(
        "创建时间："
        + (project.get("created_at") or "-")
        + " | 最近更新时间："
        + (project.get("updated_at") or "-")
    )

    if st.button("✏️ 编辑项目信息"):
        st.session_state.editing_project = True
        st.rerun()


def _render_edit_form(project: dict) -> None:
    """编辑基本信息"""
    with st.form("edit_project_form"):
        name = st.text_input("项目名称 *", value=project["name"])
        col1, col2 = st.columns(2)
        with col1:
            department = st.text_input("申报部门", value=project.get("department") or "")
        with col2:
            project_manager = st.text_input("项目负责人", value=project.get("project_manager") or "")

        col3, col4 = st.columns(2)
        with col3:
            sponsor = st.text_input("发起人", value=project.get("sponsor") or "")
        with col4:
            category = st.text_input("项目分类", value=project.get("category") or "")

        col5, col6 = st.columns(2)
        with col5:
            budget = st.number_input(
                "初始申报预算（万元）",
                min_value=0.0,
                value=float(project.get("budget") or 0),
                step=10.0,
            )
        with col6:
            st.text_input("审核后预算（只读）", value=_budget_display(project.get("approved_budget")), disabled=True)

        description = st.text_area("项目描述", value=project.get("description") or "", height=100)
        special_note = st.text_area("特殊说明", value=project.get("special_note") or "", height=90)

        col7, col8 = st.columns(2)
        with col7:
            actual_start_date = st.text_input("实际开始日期", value=project.get("actual_start_date") or "")
        with col8:
            actual_end_date = st.text_input("实际结束日期", value=project.get("actual_end_date") or "")

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            submitted = st.form_submit_button("💾 保存修改", use_container_width=True)
        with btn_col2:
            cancelled = st.form_submit_button("❌ 取消", use_container_width=True)

        if cancelled:
            st.session_state.editing_project = False
            st.rerun()

        if submitted:
            if not name.strip():
                st.error("项目名称不能为空。")
            else:
                success = update_project(
                    project["id"],
                    name=name.strip(),
                    description=description.strip(),
                    department=department.strip(),
                    sponsor=sponsor.strip(),
                    project_manager=project_manager.strip(),
                    category=category.strip(),
                    budget=budget,
                    special_note=special_note.strip(),
                    actual_start_date=actual_start_date.strip(),
                    actual_end_date=actual_end_date.strip(),
                )
                if success:
                    st.session_state.editing_project = False
                    st.success("项目信息已更新。")
                    st.rerun()
                else:
                    st.error("保存失败，请重试。")


def _render_status_history(project_id: int) -> None:
    """渲染状态历史"""
    history = get_status_history(project_id)
    if not history:
        st.info("暂无状态变更记录。")
        return

    rows = []
    for item in history:
        rows.append(
            {
                "时间": (item.get("transition_date") or "")[:16],
                "状态变更": (item.get("from_status_name") or "（创建）")
                + " → "
                + (item.get("to_status_name") or item["to_status"]),
                "动作": item["action"],
                "操作人": item["operator"],
                "审批人": item.get("approver") or "-",
                "说明": item.get("comment") or "",
                "交付物": item.get("deliverable") or "",
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_status_transition(project: dict) -> None:
    """渲染单项目状态流转"""
    st.markdown("### 当前状态：" + _get_status_name(project["current_status"]))
    st.caption("送审预算逻辑：只有进入送审中或从送审中流转出来时，才允许维护审核后预算。")

    force_mode = False
    if _is_pmo_mode():
        force_mode = st.checkbox(
            "PMO 特批强制变更",
            key="detail_force_mode_" + str(project["id"]),
        )

    if force_mode:
        transition_options = [
            {
                "to_status": status["status_code"],
                "status_name": status["status_name"],
                "requires_approval": True,
                "approver_roles": ["PMO"],
                "action_name": "PMO特批强制变更",
            }
            for status in _get_status_definitions()
            if status["status_code"] != project["current_status"]
        ]
        st.warning("已启用 PMO 特批模式，将跳过常规流转规则校验并记录特批历史。")
    else:
        transition_options = []
        for item in get_allowed_transitions(project["current_status"]):
            transition_options.append(
                {
                    "to_status": item["to_status"],
                    "status_name": item.get("to_status_name") or _get_status_name(item["to_status"]),
                    "requires_approval": bool(item["requires_approval"]),
                    "approver_roles": [item.get("approver_role") or ""],
                    "action_name": item["action_name"],
                }
            )

    if not transition_options:
        st.info("当前状态暂无可执行的下一步流转。")
        return

    option_map = {}
    option_labels = []
    for option in transition_options:
        approval_tag = " [需审批]" if option["requires_approval"] else ""
        label = option["status_name"] + approval_tag + " — " + option["action_name"]
        option_labels.append(label)
        option_map[label] = option

    selected_label = st.selectbox("目标状态", options=option_labels)
    selected_option = option_map[selected_label]

    col1, col2 = st.columns(2)
    with col1:
        operator = st.text_input(
            "操作人",
            value=_current_operator(),
            key="detail_operator_" + str(project["id"]),
        )
    with col2:
        approver_default = _current_operator() if (_is_pmo_mode() or force_mode) else ""
        approver = st.text_input(
            "审批人",
            value=approver_default,
            key="detail_approver_" + str(project["id"]),
        )

    deliverable = st.text_input(
        "交付物",
        key="detail_deliverable_" + str(project["id"]),
        placeholder="可选，例如：立项纪要 / 采购申请 / 验收报告",
    )
    comment = st.text_area(
        "变更理由",
        key="detail_comment_" + str(project["id"]),
        height=100,
        placeholder="请填写本次状态变更原因。",
    )

    if selected_option["requires_approval"]:
        role_text = "、".join(role for role in selected_option["approver_roles"] if role) or "指定审批人"
        st.info("该流转建议审批角色：" + role_text)

    adjust_budget, approved_budget = _render_budget_adjustment_inputs(
        key_prefix="detail_" + str(project["id"]),
        current_budget=float(project.get("budget") or 0),
        current_approved_budget=project.get("approved_budget"),
        enabled=transition_allows_budget_adjustment(project["current_status"], selected_option["to_status"]),
    )

    if st.button("✅ 确认变更状态", type="primary"):
        errors = []
        if not operator.strip():
            errors.append("操作人不能为空。")
        if not comment.strip():
            errors.append("变更理由不能为空。")
        if (force_mode or selected_option["requires_approval"]) and not approver.strip():
            errors.append("当前操作需要审批人，请填写审批人。")
        if adjust_budget and approved_budget is None:
            errors.append("请填写审核后预算。")

        if errors:
            for error in errors:
                st.error(error)
        else:
            result = transition_project(
                project_id=project["id"],
                to_status=selected_option["to_status"],
                operator=operator.strip(),
                approver=approver.strip() or None,
                comment=comment.strip(),
                deliverable=deliverable.strip(),
                force=force_mode,
                approved_budget=approved_budget if adjust_budget else None,
            )
            if result["success"]:
                st.success(result["message"])
                st.rerun()
            else:
                st.error(result["message"])


def render_project_detail() -> None:
    """渲染项目详情页"""
    project_id = st.session_state.selected_project_id
    if not project_id:
        st.error("未选择项目。")
        go_dashboard()
        return

    project = get_project_by_id(project_id)
    if not project:
        st.error("项目不存在。")
        go_dashboard()
        return

    st.markdown("## 📄 项目详情")
    st.markdown(
        '<span style="font-size:14px; color:#64748b;">'
        + project["project_code"]
        + "</span>&nbsp;&nbsp;"
        + _status_badge(project["current_status"]),
        unsafe_allow_html=True,
    )

    tab_info, tab_history, tab_transition = st.tabs(["📋 基本信息", "📜 状态历史", "🔄 变更状态"])
    with tab_info:
        _render_project_info(project)
    with tab_history:
        _render_status_history(project_id)
    with tab_transition:
        _render_status_transition(project)

    st.markdown("---")
    back_col1, back_col2 = st.columns(2)
    with back_col1:
        if st.button("← 返回工作台", use_container_width=True):
            go_dashboard()
    with back_col2:
        if st.button("🔄 刷新详情", use_container_width=True):
            st.rerun()


def render_import() -> None:
    """渲染批量导入页面"""
    st.markdown("## 📥 批量导入历史项目")
    st.caption("先下载模板，再上传 Excel / CSV，完成字段映射后批量导入。")

    template_bytes = _generate_import_template()
    st.download_button(
        label="📥 下载导入模板（Excel）",
        data=template_bytes,
        file_name="PMO项目导入模板.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("---")
    uploaded_file = st.file_uploader(
        "上传 Excel 或 CSV 文件",
        type=["xlsx", "xls", "csv"],
        help="支持 .xlsx / .xls / .csv 格式",
    )

    if not uploaded_file:
        if st.button("← 返回工作台"):
            go_dashboard()
        return

    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file, dtype=str)
        else:
            df = pd.read_excel(uploaded_file, dtype=str)
    except Exception as exc:
        st.error("文件读取失败：" + str(exc))
        if st.button("← 返回工作台"):
            go_dashboard()
        return

    df = df.fillna("")
    st.markdown("### 数据预览与字段映射")
    st.caption("文件共 " + str(len(df)) + " 行。")

    db_fields = {
        "project_code": "项目编号",
        "name": "项目名称",
        "description": "项目描述",
        "department": "申报部门",
        "sponsor": "发起人",
        "project_manager": "项目负责人",
        "current_status": "当前状态",
        "category": "项目分类",
        "budget": "预算(万元)",
        "approved_budget": "审核后预算(万元)",
        "special_note": "特殊说明",
        "actual_start_date": "实际开始日期",
        "actual_end_date": "实际结束日期",
    }

    file_columns = df.columns.tolist()
    mapping = {}

    map_cols = st.columns(3)
    for idx, (db_field, label) in enumerate(db_fields.items()):
        with map_cols[idx % 3]:
            default_index = 0
            for col_index, file_col in enumerate(file_columns):
                if file_col.strip() == label or file_col.strip().lower() == db_field.lower():
                    default_index = col_index + 1
                    break

            selected = st.selectbox(
                label,
                options=["（不映射）"] + file_columns,
                index=default_index,
                key="import_map_" + db_field,
            )
            if selected != "（不映射）":
                mapping[db_field] = selected

    if mapping:
        preview_rows = []
        for _, row in df.head(5).iterrows():
            preview_row = {}
            for db_field, source_col in mapping.items():
                preview_row[db_field] = str(row.get(source_col, ""))
            preview_rows.append(preview_row)
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    operator = st.text_input("操作人", value=_current_operator(), key="import_operator")

    import_col1, import_col2 = st.columns(2)
    with import_col1:
        confirm_import = st.button("✅ 确认导入", type="primary", use_container_width=True)
    with import_col2:
        if st.button("← 返回工作台", use_container_width=True):
            go_dashboard()

    if confirm_import:
        if not operator.strip():
            st.error("操作人不能为空。")
        elif "name" not in mapping:
            st.error("必须映射“项目名称”字段。")
        else:
            records = []
            for _, row in df.iterrows():
                record = {}
                for db_field, source_col in mapping.items():
                    value = str(row.get(source_col, ""))
                    record[db_field] = value if value != "nan" else ""
                records.append(record)

            with st.spinner("正在导入数据..."):
                result = batch_create_projects(records, operator=operator.strip())

            metric_col1, metric_col2, metric_col3 = st.columns(3)
            with metric_col1:
                st.metric("总数", result["total"])
            with metric_col2:
                st.metric("成功", result["success"])
            with metric_col3:
                st.metric("失败", result["failed"])

            if result["errors"]:
                with st.expander("查看导入失败详情"):
                    for item in result["errors"]:
                        st.error(
                            "第"
                            + str(item["row"])
                            + " 行 ["
                            + item["name"]
                            + "]："
                            + item["error"]
                        )

            if result["success"] > 0:
                st.success("成功导入 " + str(result["success"]) + " 个项目。")


def render_workflow() -> None:
    """渲染工作流管理"""
    st.markdown("## 🔄 工作流管理")

    tab_diagram, tab_statuses, tab_rules = st.tabs(["📊 流转图", "📋 状态定义", "📐 流转规则"])
    with tab_diagram:
        mermaid_code = generate_mermaid_diagram()
        st.markdown("### 项目全生命周期状态流转图")
        st.mermaid(mermaid_code)
        st.caption("主流程保持 11 个状态与既有规则；PMO 特批仅作为补充入口，不替代标准流程。")

    with tab_statuses:
        for status in _get_status_definitions():
            title = (
                str(status["sort_order"])
                + ". "
                + status["status_name"]
                + " ("
                + status["status_code"]
                + ")"
            )
            if status["is_terminal"]:
                title += " [终态]"
            with st.expander(title):
                left_col, right_col = st.columns(2)
                with left_col:
                    st.markdown("**状态说明：** " + (status.get("description") or "-"))
                    st.markdown("**准入条件：** " + (status.get("entry_condition") or "-"))
                    st.markdown("**退出条件：** " + (status.get("exit_condition") or "-"))
                with right_col:
                    st.markdown("**责任角色：** " + (status.get("responsible_role") or "-"))
                    st.markdown("**关键交付物：** " + (status.get("key_deliverable") or "-"))

    with tab_rules:
        rules = get_all_transition_rules()
        rows = []
        for rule in rules:
            rows.append(
                {
                    "从状态": _get_status_name(rule["from_status"]),
                    "到状态": _get_status_name(rule["to_status"]),
                    "动作": rule["action_name"],
                    "需审批": "是" if rule["requires_approval"] else "否",
                    "审批角色": rule.get("approver_role") or "-",
                    "必要交付物": rule.get("required_deliverable") or "-",
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        approval_count = sum(1 for rule in rules if rule["requires_approval"])
        st.caption(
            "共 "
            + str(len(rules))
            + " 条流转规则，其中需审批 "
            + str(approval_count)
            + " 条，直接操作 "
            + str(len(rules) - approval_count)
            + " 条。"
        )

    if st.button("← 返回工作台"):
        go_dashboard()


with st.sidebar:
    st.markdown("### 📋 PMO项目管理系统")
    st.markdown("---")

    if st.button("🏠 PMO工作台", use_container_width=True):
        go_dashboard()
    if st.button("➕ 新增项目", use_container_width=True):
        go_create()
    if st.button("📥 批量导入", use_container_width=True):
        go_import()
    if st.button("🔄 工作流管理", use_container_width=True):
        go_workflow()

    st.markdown("---")
    st.markdown("### 操作上下文")
    st.text_input("当前操作人", key="current_user")
    st.radio("当前角色", options=["PMO", "普通用户"], key="current_role", horizontal=True)

    st.markdown("---")
    st.caption(
        "当前版本重点：\n"
        "1. 四大统筹视角\n"
        "2. 稳定批量勾选\n"
        "3. 送审预算 approved_budget\n"
        "4. PMO 特批与批量确认"
    )


view = st.session_state.view

if view in {"dashboard", "list"}:
    render_dashboard()
elif view == "create":
    render_create_project()
elif view == "detail":
    render_project_detail()
elif view == "import":
    render_import()
elif view == "workflow":
    render_workflow()
else:
    render_dashboard()
