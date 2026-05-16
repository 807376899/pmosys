from __future__ import annotations

import streamlit as st

from utils.constants import DASHBOARD_FILTER_DEFAULTS


def init_session_state() -> None:
    """初始化会话状态。"""
    defaults = {
        "view": "dashboard",
        "selected_project_id": None,
        "current_user": "PMO办公室",
        "current_role": "PMO",
        "selected_project_ids": [],
        "editing_project": False,
        "batch_feedback": None,
        "pending_batch_payload": None,
    }
    defaults.update(DASHBOARD_FILTER_DEFAULTS)

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def current_operator() -> str:
    """获取当前操作人。"""
    return st.session_state.current_user.strip() or "PMO办公室"


def is_pmo_mode() -> bool:
    """是否为 PMO 模式。"""
    return st.session_state.current_role == "PMO"


def clear_selection() -> None:
    """清空项目勾选。"""
    st.session_state.selected_project_ids = []


def prune_selected_project_ids(visible_ids: set[int]) -> None:
    """过滤掉当前结果集中不可见的勾选项。"""
    st.session_state.selected_project_ids = [
        project_id for project_id in st.session_state.selected_project_ids if project_id in visible_ids
    ]


def reset_dashboard_filters() -> None:
    """重置工作台筛选。"""
    for key, value in DASHBOARD_FILTER_DEFAULTS.items():
        st.session_state[key] = value
    clear_selection()


def go_dashboard() -> None:
    """跳转工作台。"""
    st.session_state.view = "dashboard"
    st.session_state.selected_project_id = None
    st.rerun()


def go_create() -> None:
    """跳转新增项目。"""
    st.session_state.view = "create"
    st.rerun()


def go_detail(project_id: int) -> None:
    """跳转项目详情。"""
    st.session_state.view = "detail"
    st.session_state.selected_project_id = project_id
    st.session_state.editing_project = False
    st.rerun()


def go_import() -> None:
    """跳转批量导入。"""
    st.session_state.view = "import"
    st.rerun()


def go_workflow() -> None:
    """跳转工作流管理。"""
    st.session_state.view = "workflow"
    st.rerun()
