from __future__ import annotations

import streamlit as st

from components.create_project import render_create_project
from components.dashboard import render_dashboard
from components.import_page import render_import
from components.project_detail import render_project_detail
from components.workflow_page import render_workflow
from lib.database import init_database
from utils.session import (
    go_create,
    go_dashboard,
    go_import,
    go_workflow,
    init_session_state,
)


st.set_page_config(
    page_title="PMO项目管理系统",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_database()
init_session_state()


def render_sidebar() -> None:
    """渲染侧边栏导航。"""
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
            "1. 项目状态视角切换\n"
            "2. 轻量筛选栏\n"
            "3. 稳定批量勾选\n"
            "4. 组件化代码结构"
        )


def main() -> None:
    """主入口。"""
    render_sidebar()

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


if __name__ == "__main__":
    main()
