from __future__ import annotations

import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st

from lib.database import (
    batch_transition_projects,
    get_allowed_transitions,
    get_departments,
    get_projects,
    transition_allows_budget_adjustment,
)
from utils.constants import GROUP_FILTERS, GROUP_ORDER
from utils.exports import build_batch_failure_export_bytes, build_export_bytes
from utils.filters import (
    apply_dashboard_filters,
    build_group_counts,
    build_group_summary,
    filter_projects_by_group,
    get_declaration_year,
    get_implementation_year,
    get_year_options,
)
from utils.formatters import (
    budget_display,
    get_status_definitions,
    get_status_name,
    get_status_order_map,
)
from utils.session import (
    clear_selection,
    current_operator,
    go_create,
    go_detail,
    go_import,
    go_workflow,
    is_pmo_mode,
    prune_selected_project_ids,
    reset_dashboard_filters,
)
from utils.widgets import render_budget_adjustment_inputs


def _build_selection_editor_key(projects: list[dict]) -> str:
    """基于当前结果集生成稳定勾选面板 key。"""
    raw = "|".join(str(project["id"]) for project in projects)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]
    return "dashboard_selection_editor_" + digest


def _build_common_transition_options(projects: list[dict]) -> list[dict]:
    """计算一组项目的共同合法下一状态。"""
    if not projects:
        return []

    unique_statuses = sorted({project["current_status"] for project in projects})
    transition_maps: list[dict[str, dict]] = []

    for status_code in unique_statuses:
        option_map: dict[str, dict] = {}
        for item in get_allowed_transitions(status_code):
            option_map[item["to_status"]] = {
                "to_status": item["to_status"],
                "status_name": item.get("to_status_name") or get_status_name(item["to_status"]),
                "requires_approval": bool(item["requires_approval"]),
                "approver_roles": {item.get("approver_role") or ""},
                "action_names": {item["action_name"]},
            }
        transition_maps.append(option_map)

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
                "status_name": get_status_name(to_status),
                "requires_approval": requires_approval,
                "approver_roles": sorted(role for role in approver_roles if role),
                "action_names": sorted(action_names),
            }
        )

    merged.sort(key=lambda item: get_status_order_map().get(item["to_status"], 999))
    return merged


def _build_force_transition_options(projects: list[dict]) -> list[dict]:
    """构建 PMO 特批可选状态。"""
    options = []
    for status in get_status_definitions():
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
    """批量场景是否允许调整审核后预算。"""
    return any(
        transition_allows_budget_adjustment(project["current_status"], to_status)
        for project in projects
    )


def _build_main_table(projects: list[dict]) -> pd.DataFrame:
    """构建主展示表格。"""
    rows = []
    for project in projects:
        rows.append(
            {
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "当前状态": get_status_name(project["current_status"]),
                "申报部门": project.get("department") or "-",
                "项目负责人": project.get("project_manager") or "-",
                "申报年份": get_declaration_year(project) or "-",
                "实施年份": get_implementation_year(project) or "-",
                "初始申报预算(万元)": float(project.get("budget") or 0),
                "审核后预算(万元)": project.get("approved_budget"),
                "状态更新时间": project.get("status_updated_at") or "-",
                "特殊说明": project.get("special_note") or "-",
            }
        )
    return pd.DataFrame(rows)


def _build_selection_table(projects: list[dict], selected_ids: list[int]) -> pd.DataFrame:
    """构建批量勾选面板。"""
    selected_set = set(selected_ids)
    rows = []
    for project in projects:
        rows.append(
            {
                "选择": project["id"] in selected_set,
                "project_id": project["id"],
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "当前状态": get_status_name(project["current_status"]),
                "申报部门": project.get("department") or "-",
            }
        )
    return pd.DataFrame(rows)


def _render_group_buttons(projects: list[dict]) -> None:
    """渲染项目状态视角按钮。"""
    counts = build_group_counts(projects)
    st.markdown("### 项目状态")

    cols = st.columns(len(GROUP_ORDER))
    for col, group_key in zip(cols, GROUP_ORDER):
        with col:
            active = st.session_state.dashboard_group_filter == group_key
            label = GROUP_FILTERS[group_key]["label"]
            count_text = str(counts.get(group_key, 0))
            button_label = f"{label} ({count_text})"
            if active:
                button_label = "✓ " + button_label
            if st.button(button_label, key="group_filter_" + group_key, use_container_width=True):
                st.session_state.dashboard_group_filter = group_key
                clear_selection()
                st.rerun()


def _render_batch_feedback() -> None:
    """渲染批量处理结果反馈。"""
    feedback = st.session_state.batch_feedback
    if not feedback:
        return

    result_col1, result_col2, result_col3, result_col4 = st.columns([1, 1, 1, 0.8])
    with result_col1:
        st.metric("本次处理总数", feedback["total"])
    with result_col2:
        st.metric("成功", feedback["success"])
    with result_col3:
        st.metric("失败", feedback["failed"])
    with result_col4:
        if st.button("关闭提示", use_container_width=True):
            st.session_state.batch_feedback = None
            st.rerun()

    if feedback["failed"] == 0:
        st.success("批量操作已完成。")
        return

    st.warning("批量操作已完成，但存在失败项目。")
    failure_bytes = build_batch_failure_export_bytes(feedback["errors"])
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
                st.error(item["project_code"] + " | " + item["name"] + "：" + item["error"])


@st.dialog("确认批量操作")
def _render_batch_confirmation_dialog() -> None:
    """批量操作确认弹窗。"""
    payload = st.session_state.pending_batch_payload
    if not payload:
        return

    projects = payload["projects"]
    from_summary = build_group_summary(projects)
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
        st.info("本次将统一写入审核后预算：" + budget_display(payload["approved_budget"]) + " 万元。")

    preview_rows = []
    for project in projects:
        preview_rows.append(
            {
                "项目编号": project["project_code"],
                "项目名称": project["name"],
                "当前状态": get_status_name(project["current_status"]),
                "初始申报预算(万元)": float(project.get("budget") or 0),
                "审核后预算(万元)": project.get("approved_budget"),
            }
        )
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

    col1, col2 = st.columns(2)
    with col1:
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
            clear_selection()
            st.rerun()
    with col2:
        if st.button("取消", use_container_width=True):
            st.session_state.pending_batch_payload = None
            st.rerun()


def render_dashboard() -> None:
    """渲染 PMO 统筹工作台。"""
    st.markdown("## PMO统筹工作台")
    st.caption("通过“项目状态”视角切换，再配合轻量筛选完成日常统筹。")

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
            st.rerun()
    with toolbar_cols[4]:
        if st.button("清空筛选", use_container_width=True):
            reset_dashboard_filters()
            st.rerun()

    _render_batch_feedback()

    keyword_col, department_col, detail_status_col = st.columns([2.2, 1.2, 1.2])
    with keyword_col:
        keyword = st.text_input(
            "关键词",
            key="dashboard_keyword",
            placeholder="项目编号 / 名称 / 描述 / 发起人 / 特殊说明",
        )
    with department_col:
        department_options = ["全部"] + get_departments()
        department = st.selectbox(
            "申报部门",
            options=department_options,
            key="dashboard_department",
        )
    with detail_status_col:
        detail_status_options = ["全部"] + [status["status_name"] for status in get_status_definitions()]
        detail_status = st.selectbox(
            "细分状态",
            options=detail_status_options,
            key="dashboard_detail_status",
        )

    query_department = None if department == "全部" else department
    base_projects = get_projects(
        keyword=keyword.strip() or None,
        department=query_department,
    )

    declaration_year_options = ["全部"] + get_year_options(base_projects, get_declaration_year)
    implementation_year_options = ["全部"] + get_year_options(base_projects, get_implementation_year)

    with st.expander("更多筛选", expanded=False):
        year_col1, year_col2 = st.columns(2)
        with year_col1:
            declaration_year = st.selectbox(
                "申报年份",
                options=declaration_year_options,
                key="dashboard_declaration_year",
            )
        with year_col2:
            implementation_year = st.selectbox(
                "实施年份",
                options=implementation_year_options,
                key="dashboard_implementation_year",
            )

    filtered_projects = apply_dashboard_filters(
        base_projects,
        detail_status_name=detail_status,
        declaration_year=st.session_state.dashboard_declaration_year,
        implementation_year=st.session_state.dashboard_implementation_year,
    )

    _render_group_buttons(filtered_projects)

    visible_projects = filter_projects_by_group(
        filtered_projects,
        st.session_state.dashboard_group_filter,
    )
    visible_ids = {project["id"] for project in visible_projects}
    prune_selected_project_ids(visible_ids)

    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
    with summary_col1:
        st.metric("当前结果数", len(visible_projects))
    with summary_col2:
        st.metric("已勾选", len(st.session_state.selected_project_ids))
    with summary_col3:
        budget_sum = sum(float(project.get("budget") or 0) for project in visible_projects)
        st.metric("初始申报预算合计（万元）", f"{budget_sum:,.1f}")
    with summary_col4:
        approved_budget_sum = sum(
            float(project["approved_budget"])
            for project in visible_projects
            if project.get("approved_budget") is not None
        )
        st.metric("审核后预算合计（万元）", f"{approved_budget_sum:,.1f}")

    if not visible_projects:
        st.info("当前筛选条件下暂无项目。")
        if st.session_state.pending_batch_payload:
            _render_batch_confirmation_dialog()
        return

    export_col1, export_col2, export_col3 = st.columns([1, 1, 2.5])
    with export_col1:
        st.download_button(
            "导出当前结果",
            data=build_export_bytes(visible_projects),
            file_name="PMO筛选结果_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with export_col2:
        if st.button("清空勾选", use_container_width=True):
            clear_selection()
            st.rerun()
    with export_col3:
        detail_options = {
            project["project_code"] + " | " + project["name"]: project["id"]
            for project in visible_projects
        }
        quick_label = st.selectbox("快速查看项目详情", options=list(detail_options.keys()))
        if st.button("查看详情", use_container_width=True):
            go_detail(detail_options[quick_label])

    st.dataframe(
        _build_main_table(visible_projects),
        use_container_width=True,
        hide_index=True,
        height=520,
        column_config={
            "初始申报预算(万元)": st.column_config.NumberColumn("初始申报预算(万元)", format="%.2f"),
            "审核后预算(万元)": st.column_config.NumberColumn("审核后预算(万元)", format="%.2f"),
            "特殊说明": st.column_config.TextColumn("特殊说明", width="large"),
        },
    )

    with st.expander(f"批量勾选（已选 {len(st.session_state.selected_project_ids)} 项）", expanded=bool(st.session_state.selected_project_ids)):
        action_col1, action_col2 = st.columns(2)
        with action_col1:
            if st.button("全选当前结果", use_container_width=True):
                st.session_state.selected_project_ids = [project["id"] for project in visible_projects]
                st.rerun()
        with action_col2:
            st.caption("勾选会自动保存，无需再点“更新勾选结果”。")

        editor_key = _build_selection_editor_key(visible_projects)
        edited_df = st.data_editor(
            _build_selection_table(visible_projects, st.session_state.selected_project_ids),
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            height=min(420, max(180, 80 + len(visible_projects) * 35)),
            column_config={
                "选择": st.column_config.CheckboxColumn("选择", help="勾选后用于批量操作"),
                "project_id": None,
            },
            disabled=["project_id", "项目编号", "项目名称", "当前状态", "申报部门"],
            key=editor_key,
        )
        selected_ids = edited_df.loc[edited_df["选择"], "project_id"].tolist()
        st.session_state.selected_project_ids = [int(project_id) for project_id in selected_ids]

    selected_projects = [
        project for project in visible_projects if project["id"] in st.session_state.selected_project_ids
    ]
    if not selected_projects:
        if st.session_state.pending_batch_payload:
            _render_batch_confirmation_dialog()
        return

    st.markdown("### 批量操作")
    st.caption("当前已选中 " + str(len(selected_projects)) + " 个项目：" + build_group_summary(selected_projects))

    force_mode = False
    if is_pmo_mode():
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
            value=current_operator(),
            key="dashboard_batch_operator",
        )
        deliverable = st.text_input(
            "交付物",
            key="dashboard_batch_deliverable",
            placeholder="可选，例如：立项批复 / 采购申请 / 验收报告",
        )
    with batch_col2:
        default_approver = current_operator() if (is_pmo_mode() or force_mode) else ""
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
    adjust_budget, approved_budget = render_budget_adjustment_inputs(
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
                "target_status_name": get_status_name(selected_option["to_status"]),
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
