from __future__ import annotations

import streamlit as st

from lib.database import create_project, generate_project_code
from utils.session import current_operator, go_dashboard, go_detail


def render_create_project() -> None:
    """渲染新增项目页面。"""
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
            operator = st.text_input("操作人 *", value=current_operator())

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
