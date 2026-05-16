from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.database import generate_mermaid_diagram, get_all_transition_rules
from utils.formatters import get_status_definitions, get_status_name
from utils.session import go_dashboard


def render_workflow() -> None:
    """渲染工作流管理页。"""
    st.markdown("## 🔄 工作流管理")

    tab_diagram, tab_statuses, tab_rules = st.tabs(["📊 流转图", "📋 状态定义", "📚 流转规则"])
    with tab_diagram:
        st.markdown("### 项目全生命周期状态流转图")
        st.mermaid(generate_mermaid_diagram())
        st.caption("保持现有 11 个状态和既有规则，PMO 特批仅作为补充入口。")

    with tab_statuses:
        for status in get_status_definitions():
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
                    "从状态": get_status_name(rule["from_status"]),
                    "到状态": get_status_name(rule["to_status"]),
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
