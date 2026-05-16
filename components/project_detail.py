from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.database import (
    get_allowed_transitions,
    get_project_by_id,
    get_status_history,
    transition_allows_budget_adjustment,
    transition_project,
    update_project,
)
from utils.formatters import budget_display, get_status_definitions, get_status_name, status_badge
from utils.session import current_operator, go_dashboard, is_pmo_mode
from utils.widgets import render_budget_adjustment_inputs


def _render_project_info(project: dict) -> None:
    """渲染项目基本信息。"""
    if st.session_state.editing_project:
        _render_edit_form(project)
    else:
        _render_info_display(project)


def _render_info_display(project: dict) -> None:
    """只读展示项目信息。"""
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**项目编号：** " + project["project_code"])
        st.markdown("**项目名称：** " + project["name"])
        st.markdown("**申报部门：** " + (project.get("department") or "-"))
        st.markdown("**项目负责人：** " + (project.get("project_manager") or "-"))
        st.markdown("**发起人：** " + (project.get("sponsor") or "-"))
    with col2:
        st.markdown("**当前状态：** " + get_status_name(project["current_status"]))
        st.markdown("**项目分类：** " + (project.get("category") or "-"))
        st.markdown("**初始申报预算：** " + budget_display(project.get("budget")) + " 万元")
        st.markdown("**审核后预算：** " + budget_display(project.get("approved_budget")) + " 万元")
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
    """编辑基本信息。"""
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
            st.text_input("审核后预算（只读）", value=budget_display(project.get("approved_budget")), disabled=True)

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
    """渲染状态历史。"""
    history = get_status_history(project_id)
    if not history:
        st.info("暂无状态变更记录。")
        return

    rows = []
    for item in history:
        rows.append(
            {
                "时间": (item.get("transition_date") or "")[:16],
                "状态变更": (item.get("from_status_name") or "（创建）") + " → " + (item.get("to_status_name") or item["to_status"]),
                "动作": item["action"],
                "操作人": item["operator"],
                "审批人": item.get("approver") or "-",
                "说明": item.get("comment") or "",
                "交付物": item.get("deliverable") or "",
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_status_transition(project: dict) -> None:
    """渲染单项目状态流转。"""
    st.markdown("### 当前状态：" + get_status_name(project["current_status"]))
    st.caption("送审预算逻辑：只有进入送审中或从送审中流转出来时，才允许维护审核后预算。")

    force_mode = False
    if is_pmo_mode():
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
            for status in get_status_definitions()
            if status["status_code"] != project["current_status"]
        ]
        st.warning("已启用 PMO 特批模式，将跳过常规流转规则校验并记录特批历史。")
    else:
        transition_options = []
        for item in get_allowed_transitions(project["current_status"]):
            transition_options.append(
                {
                    "to_status": item["to_status"],
                    "status_name": item.get("to_status_name") or get_status_name(item["to_status"]),
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
            value=current_operator(),
            key="detail_operator_" + str(project["id"]),
        )
    with col2:
        approver_default = current_operator() if (is_pmo_mode() or force_mode) else ""
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

    adjust_budget, approved_budget = render_budget_adjustment_inputs(
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
    """渲染项目详情页。"""
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
        + status_badge(project["current_status"]),
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
