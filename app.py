"""
PMO项目管理系统 - Streamlit 主应用

功能模块：
1. 项目列表：状态统计卡片 + 筛选 + 导出Excel + 下载导入模板 + 批量导入入口
2. 新增项目：自动生成项目编号(PMO-年份-序号)，精简字段
3. 项目详情：基本信息展示 + 编辑 + 状态流转(含严格合规校验)
4. 批量导入：上传CSV/Excel → 字段映射 → 导入确认 → 结果统计
5. 工作流管理：Mermaid流转图 + 状态定义 + 流转规则

字段精简版（移除 priority、planned_start_date、planned_end_date）
"""

import streamlit as st
import pandas as pd
import io
from datetime import datetime

from lib.database import (
    init_database,
    create_project,
    get_projects,
    get_project_by_id,
    update_project,
    get_status_history,
    get_status_stats,
    get_departments,
    get_project_managers,
    get_allowed_transitions,
    transition_project,
    get_all_statuses,
    get_all_transition_rules,
    generate_project_code,
    generate_mermaid_diagram,
    batch_create_projects,
    VALID_STATUS_CODES,
)


# ============================================================
# 页面配置（必须是第一个 Streamlit 命令）
# ============================================================
st.set_page_config(
    page_title="PMO项目管理系统",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 初始化数据库（仅首次运行时生效）
init_database()

# 获取状态定义缓存（避免每次查库）
@st.cache_data(ttl=30)
def _get_status_map() -> dict:
    """获取状态码→中文名的映射"""
    statuses = get_all_statuses()
    return {s["status_code"]: s["status_name"] for s in statuses}


def _get_status_color(status_code: str) -> str:
    """获取状态对应的颜色"""
    statuses = get_all_statuses()
    for s in statuses:
        if s["status_code"] == status_code:
            return s["color"]
    return "#6B7280"


# ============================================================
# Session State 初始化
# ============================================================
def init_session_state():
    """初始化会话状态变量"""
    if "view" not in st.session_state:
        st.session_state.view = "list"
    if "selected_project_id" not in st.session_state:
        st.session_state.selected_project_id = None
    if "refresh_counter" not in st.session_state:
        st.session_state.refresh_counter = 0


init_session_state()


# ============================================================
# 页面导航辅助函数
# ============================================================
def go_list():
    """跳转到项目列表"""
    st.session_state.view = "list"
    st.session_state.selected_project_id = None
    st.rerun()


def go_create():
    """跳转到新增项目"""
    st.session_state.view = "create"
    st.rerun()


def go_detail(project_id: int):
    """跳转到项目详情"""
    st.session_state.view = "detail"
    st.session_state.selected_project_id = project_id
    st.rerun()


def go_import():
    """跳转到批量导入"""
    st.session_state.view = "import"
    st.rerun()


def go_workflow():
    """跳转到工作流管理"""
    st.session_state.view = "workflow"
    st.rerun()


# ============================================================
# 状态徽章 HTML 生成（用于列表展示）
# ============================================================
def status_badge(status_code: str, status_name: str, color: str) -> str:
    """生成状态徽章的 HTML 片段"""
    style = (
        "display:inline-block; padding:2px 10px; border-radius:12px; "
        "color:white; font-size:12px; font-weight:500; "
        "background-color:" + color + ";"
    )
    return '<span style="' + style + '">' + status_name + '</span>'


# ============================================================
# 项目列表页面
# ============================================================
def render_project_list():
    """渲染项目列表页面"""

    # ---- 顶部操作栏 ----
    col_title, col_btns = st.columns([3, 2])
    with col_title:
        st.markdown("## 📋 项目列表")
    with col_btns:
        btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
        with btn_col1:
            if st.button("➕ 新增项目", use_container_width=True):
                go_create()
        with btn_col2:
            if st.button("📥 批量导入", use_container_width=True):
                go_import()
        with btn_col3:
            if st.button("🔄 刷新", use_container_width=True):
                st.session_state.refresh_counter += 1
                st.rerun()
        with btn_col4:
            if st.button("📊 导出Excel", use_container_width=True):
                _export_projects_excel()

    # ---- 状态统计卡片 ----
    st.markdown("---")
    stats = get_status_stats()
    status_cols = st.columns(len(stats))
    for i, stat in enumerate(stats):
        with status_cols[i]:
            label = stat["status_name"]
            count = stat["project_count"]
            color = stat["color"]
            st.markdown(
                '<div style="text-align:center; padding:8px; '
                'border-left:4px solid ' + color + '; '
                'background:#f9fafb; border-radius:4px; margin:2px;">'
                '<div style="font-size:24px; font-weight:700; color:' + color + ';">'
                + str(count) + '</div>'
                '<div style="font-size:12px; color:#6b7280;">' + label + '</div>'
                '</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ---- 筛选栏 ----
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        status_filter = st.selectbox(
            "按状态筛选",
            options=["全部"] + [s["status_name"] for s in stats],
            index=0,
            key="status_filter",
        )
    with filter_col2:
        departments = get_departments()
        dept_filter = st.selectbox(
            "按部门筛选",
            options=["全部"] + departments,
            index=0,
            key="dept_filter",
        )
    with filter_col3:
        managers = get_project_managers()
        mgr_filter = st.selectbox(
            "按负责人筛选",
            options=["全部"] + managers,
            index=0,
            key="mgr_filter",
        )
    with filter_col4:
        keyword = st.text_input("关键词搜索", placeholder="编号/名称/描述", key="keyword_search")

    # ---- 将筛选条件转换为数据库查询参数 ----
    status_map = _get_status_map()
    status_code_map = {v: k for k, v in status_map.items()}
    query_status = status_code_map.get(status_filter) if status_filter != "全部" else None
    query_dept = dept_filter if dept_filter != "全部" else None
    query_mgr = mgr_filter if mgr_filter != "全部" else None

    # ---- 查询项目列表 ----
    projects = get_projects(
        status=query_status,
        keyword=keyword if keyword else None,
        department=query_dept,
        project_manager=query_mgr,
    )

    if not projects:
        st.info("暂无项目数据，点击「新增项目」开始创建。")
        return

    # ---- 以卡片形式展示项目列表 ----
    for proj in projects:
        status_name = status_map.get(proj["current_status"], proj["current_status"])
        color = _get_status_color(proj["current_status"])

        # 项目卡片布局
        with st.container():
            card_col1, card_col2 = st.columns([6, 1])
            with card_col1:
                # 第一行：项目编号 + 名称 + 状态徽章
                badge_html = status_badge(proj["current_status"], status_name, color)
                header_html = (
                    '<div style="margin-bottom:4px;">'
                    '<span style="font-weight:700; font-size:16px;">'
                    + proj["name"] + '</span>'
                    '&nbsp;&nbsp;'
                    '<span style="color:#6b7280; font-size:13px;">'
                    + proj["project_code"] + '</span>'
                    '&nbsp;&nbsp;'
                    + badge_html
                    + '</div>'
                )
                st.markdown(header_html, unsafe_allow_html=True)

                # 第二行：部门 + 负责人 + 预算 + 更新时间
                info_parts = []
                if proj.get("department"):
                    info_parts.append("部门: " + proj["department"])
                if proj.get("project_manager"):
                    info_parts.append("负责人: " + proj["project_manager"])
                if proj.get("budget"):
                    info_parts.append("预算: " + str(proj["budget"]) + "万元")
                if proj.get("updated_at"):
                    info_parts.append("更新: " + proj["updated_at"][:16])

                if info_parts:
                    st.markdown(
                        '<div style="color:#6b7280; font-size:13px;">'
                        + "&nbsp;&nbsp;|&nbsp;&nbsp;".join(info_parts)
                        + '</div>',
                        unsafe_allow_html=True,
                    )

            with card_col2:
                if st.button("查看详情", key="view_" + str(proj["id"])):
                    go_detail(proj["id"])

            st.divider()


def _export_projects_excel():
    """导出当前项目列表为 Excel 文件"""
    projects = get_projects()
    if not projects:
        st.warning("没有可导出的项目数据")
        return

    status_map = _get_status_map()

    # 构建导出数据
    export_data = []
    for p in projects:
        export_data.append({
            "项目编号": p["project_code"],
            "项目名称": p["name"],
            "申报部门": p.get("department", ""),
            "项目负责人": p.get("project_manager", ""),
            "当前状态": status_map.get(p["current_status"], p["current_status"]),
            "项目分类": p.get("category", ""),
            "预算(万元)": p.get("budget", 0),
            "发起人": p.get("sponsor", ""),
            "实际开始日期": p.get("actual_start_date", ""),
            "实际结束日期": p.get("actual_end_date", ""),
            "创建时间": p.get("created_at", ""),
            "更新时间": p.get("updated_at", ""),
        })

    df = pd.DataFrame(export_data)

    # 生成 Excel 文件到内存
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="项目列表")
    output.seek(0)

    # 触发下载
    filename = "PMO项目列表_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
    st.download_button(
        label="📥 下载导出文件",
        data=output.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ============================================================
# 下载导入模板
# ============================================================
def _generate_import_template() -> bytes:
    """
    生成批量导入模板 Excel 文件。

    包含：
    - 说明sheet：字段说明和使用注意事项
    - 模板sheet：带示例数据的标准模板
    """
    # 模板数据（含示例行）
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
            "当前状态": "implementing",
            "项目分类": "基础设施",
            "预算(万元)": 200.0,
            "实际开始日期": "2025-06-01",
            "实际结束日期": "",
        },
    ]

    # 说明数据
    instructions_data = [
        {"字段名": "项目编号", "说明": "项目唯一编号，留空则自动生成(PMO-年份-序号)", "是否必填": "否", "示例": "PMO-2026-0001"},
        {"字段名": "项目名称", "说明": "项目名称", "是否必填": "是", "示例": "智慧办公平台升级"},
        {"字段名": "项目描述", "说明": "项目的简要描述", "是否必填": "否", "示例": "对现有办公平台进行智能化升级"},
        {"字段名": "申报部门", "说明": "项目申报的部门", "是否必填": "否", "示例": "信息中心"},
        {"字段名": "发起人", "说明": "项目发起人", "是否必填": "否", "示例": "张主任"},
        {"字段名": "项目负责人", "说明": "项目的主要负责人", "是否必填": "否", "示例": "李工"},
        {"字段名": "当前状态", "说明": "项目的当前状态，支持英文状态码或中文名称。无效状态默认设为草稿", "是否必填": "否(默认draft)", "示例": "draft / 草稿"},
        {"字段名": "项目分类", "说明": "项目分类", "是否必填": "否", "示例": "信息化建设"},
        {"字段名": "预算(万元)", "说明": "项目预算金额（单位：万元）", "是否必填": "否(默认0)", "示例": "100.0"},
        {"字段名": "实际开始日期", "说明": "项目实际开始日期，格式 YYYY-MM-DD", "是否必填": "否", "示例": "2025-06-01"},
        {"字段名": "实际结束日期", "说明": "项目实际结束日期，格式 YYYY-MM-DD", "是否必填": "否", "示例": "2025-12-31"},
    ]

    # 合法状态列表
    status_list = [
        {"状态码": "draft", "中文名": "草稿", "说明": "项目负责人提交项目申报"},
        {"状态码": "under_review", "中文名": "评审中", "说明": "评审委员会评审可行性、必要性"},
        {"状态码": "established", "中文名": "已立项", "说明": "评审通过，正式立项"},
        {"状态码": "submission_review", "中文名": "送审中", "说明": "部分项目需送上级/财政审批"},
        {"状态码": "procuring", "中文名": "采购中", "说明": "根据资金安排进行采购"},
        {"状态码": "implementing", "中文名": "实施中", "说明": "项目进入实施阶段"},
        {"状态码": "trial", "中文名": "试用中", "说明": "成果进入试用"},
        {"状态码": "accepting", "中文名": "验收中", "说明": "组织验收评审"},
        {"状态码": "closed", "中文名": "已关闭", "说明": "验收通过，正式关闭归档"},
        {"状态码": "suspended", "中文名": "已暂停", "说明": "项目暂时搁置"},
        {"状态码": "terminated", "中文名": "已终止", "说明": "项目提前终止"},
    ]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(instructions_data).to_excel(writer, index=False, sheet_name="字段说明")
        pd.DataFrame(status_list).to_excel(writer, index=False, sheet_name="合法状态列表")
        pd.DataFrame(template_data).to_excel(writer, index=False, sheet_name="导入模板(请复制此sheet)")

    output.seek(0)
    return output.getvalue()


# ============================================================
# 新增项目页面
# ============================================================
def render_create_project():
    """渲染新增项目页面（项目编号自动生成）"""

    st.markdown("## ➕ 新增项目")
    st.markdown("项目创建后默认为**草稿**状态，项目编号由系统自动生成。")

    with st.form("create_project_form"):
        # 项目编号：自动生成，不允许手动输入
        auto_code = generate_project_code()
        st.text_input("项目编号（自动生成）", value=auto_code, disabled=True)

        # 项目名称（必填）
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
            budget = st.number_input("预算（万元）", min_value=0.0, step=10.0, value=0.0)

        description = st.text_area("项目描述", placeholder="请简要描述项目内容", height=100)

        # 操作人（后续接入用户系统后可自动获取）
        operator = st.text_input("操作人", value="", placeholder="请输入您的姓名")

        submit_col1, submit_col2 = st.columns(2)
        with submit_col1:
            submitted = st.form_submit_button("✅ 创建项目", use_container_width=True)
        with submit_col2:
            cancelled = st.form_submit_button("← 返回列表", use_container_width=True)

        if cancelled:
            go_list()

        if submitted:
            if not name.strip():
                st.error("项目名称不能为空！")
            elif not operator.strip():
                st.error("请填写操作人！")
            else:
                try:
                    new_id = create_project(
                        name=name.strip(),
                        project_code=auto_code,
                        description=description.strip(),
                        department=department.strip(),
                        sponsor=sponsor.strip(),
                        project_manager=project_manager.strip(),
                        category=category.strip(),
                        budget=budget,
                        operator=operator.strip(),
                    )
                    st.success("项目创建成功！编号: " + auto_code)
                    st.balloons()
                    # 延迟跳转到详情页
                    go_detail(new_id)
                except Exception as e:
                    st.error("创建失败: " + str(e))


# ============================================================
# 项目详情页面
# ============================================================
def render_project_detail():
    """渲染项目详情页面"""

    project_id = st.session_state.selected_project_id
    if not project_id:
        st.error("未选择项目")
        go_list()
        return

    project = get_project_by_id(project_id)
    if not project:
        st.error("项目不存在")
        go_list()
        return

    status_map = _get_status_map()
    current_status_name = status_map.get(project["current_status"], project["current_status"])
    current_color = _get_status_color(project["current_status"])

    # ---- 页面标题 ----
    st.markdown("## 📄 项目详情")
    st.markdown(
        '<span style="font-size:14px; color:#6b7280;">'
        + project["project_code"] + '</span>'
        '&nbsp;&nbsp;'
        + status_badge(project["current_status"], current_status_name, current_color),
        unsafe_allow_html=True,
    )

    # ---- Tab 切换 ----
    tab_info, tab_history, tab_transition = st.tabs([
        "📋 基本信息", "📜 状态历史", "🔄 变更状态",
    ])

    # ==== Tab1: 基本信息 ====
    with tab_info:
        _render_project_info(project)

    # ==== Tab2: 状态历史 ====
    with tab_history:
        _render_status_history(project_id)

    # ==== Tab3: 变更状态 ====
    with tab_transition:
        _render_status_transition(project, status_map)

    # ---- 底部返回按钮 ----
    st.markdown("---")
    col_back1, col_back2, col_back3 = st.columns([1, 1, 2])
    with col_back1:
        if st.button("← 返回列表"):
            go_list()
    with col_back2:
        if st.button("🔄 刷新"):
            st.rerun()


def _render_project_info(project: dict):
    """渲染项目基本信息（含编辑功能）"""

    # 显示模式 / 编辑模式切换
    if "editing_project" not in st.session_state:
        st.session_state.editing_project = False

    if st.session_state.editing_project:
        _render_edit_form(project)
    else:
        _render_info_display(project)


def _render_info_display(project: dict):
    """以只读方式展示项目信息"""

    status_map = _get_status_map()

    # 基本信息
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**项目编号:** " + project["project_code"])
        st.markdown("**项目名称:** " + project["name"])
        st.markdown("**申报部门:** " + (project.get("department") or "-"))
        st.markdown("**项目负责人:** " + (project.get("project_manager") or "-"))
    with col2:
        st.markdown("**当前状态:** " + status_map.get(project["current_status"], project["current_status"]))
        st.markdown("**发起人:** " + (project.get("sponsor") or "-"))
        st.markdown("**项目分类:** " + (project.get("category") or "-"))
        st.markdown("**预算:** " + str(project.get("budget", 0)) + " 万元")

    st.markdown("**项目描述:**")
    st.markdown(project.get("description") or "（暂无描述）")

    # 日期信息
    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**实际开始日期:** " + (project.get("actual_start_date") or "-"))
    with col4:
        st.markdown("**实际结束日期:** " + (project.get("actual_end_date") or "-"))

    # 时间戳
    st.markdown("---")
    st.markdown(
        '<span style="color:#9ca3af; font-size:12px;">'
        '创建时间: ' + (project.get("created_at") or "-")
        + '&nbsp;&nbsp;|&nbsp;&nbsp;'
        + '更新时间: ' + (project.get("updated_at") or "-")
        + '</span>',
        unsafe_allow_html=True,
    )

    # 编辑按钮
    if st.button("✏️ 编辑信息"):
        st.session_state.editing_project = True
        st.rerun()


def _render_edit_form(project: dict):
    """编辑项目基本信息的表单"""
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
                "预算（万元）",
                min_value=0.0,
                step=10.0,
                value=float(project.get("budget") or 0),
            )

        description = st.text_area(
            "项目描述",
            value=project.get("description") or "",
            height=100,
        )

        col7, col8 = st.columns(2)
        with col7:
            actual_start = st.text_input("实际开始日期", value=project.get("actual_start_date") or "")
        with col8:
            actual_end = st.text_input("实际结束日期", value=project.get("actual_end_date") or "")

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
                st.error("项目名称不能为空！")
            else:
                update_data = {
                    "name": name.strip(),
                    "description": description.strip(),
                    "department": department.strip(),
                    "sponsor": sponsor.strip(),
                    "project_manager": project_manager.strip(),
                    "category": category.strip(),
                    "budget": budget,
                    "actual_start_date": actual_start.strip(),
                    "actual_end_date": actual_end.strip(),
                }
                success = update_project(project["id"], **update_data)
                if success:
                    st.success("项目信息更新成功！")
                    st.session_state.editing_project = False
                    st.rerun()
                else:
                    st.error("更新失败，请重试")


def _render_status_history(project_id: int):
    """以表格形式渲染状态流转历史"""

    history = get_status_history(project_id)
    if not history:
        st.info("暂无状态变更记录")
        return

    # 构建展示用的 DataFrame
    rows = []
    for h in history:
        from_name = h.get("from_status_name") or "（创建）"
        to_name = h.get("to_status_name", h["to_status"])
        arrow = from_name + " → " + to_name
        approver_str = h.get("approver") or "-"
        date_str = h.get("transition_date", "")[:16]

        rows.append({
            "时间": date_str,
            "状态变更": arrow,
            "动作": h["action"],
            "操作人": h["operator"],
            "审批人": approver_str,
            "说明": h.get("comment") or "",
            "交付物": h.get("deliverable") or "",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_status_transition(project: dict, status_map: dict):
    """渲染状态变更操作区域"""

    current_status = project["current_status"]
    current_status_name = status_map.get(current_status, current_status)

    st.markdown("### 当前状态: " + current_status_name)

    # 查询允许的流转规则
    allowed = get_allowed_transitions(current_status)

    if not allowed:
        st.info("当前状态没有允许的流转操作（可能已是终态）")
        return

    # 构建选项列表
    options = []
    for t in allowed:
        to_name = t.get("to_status_name", t["to_status"])
        approval_tag = " [需审批]" if t["requires_approval"] else ""
        options.append({
            "label": to_name + approval_tag + " — " + t["action_name"],
            "to_status": t["to_status"],
            "requires_approval": bool(t["requires_approval"]),
            "approver_role": t.get("approver_role", ""),
        })

    # 选择目标状态
    option_labels = [o["label"] for o in options]
    selected_label = st.selectbox("选择目标状态", option_labels)

    # 找到选中的选项
    selected = None
    for o in options:
        if o["label"] == selected_label:
            selected = o
            break

    if not selected:
        return

    # 显示流转提示
    if selected["requires_approval"]:
        st.warning("⚠️ 此流转需要审批，审批角色: " + str(selected["approver_role"]))
    else:
        st.info("ℹ️ 此流转为直接操作，无需审批")

    # 填写流转信息
    operator = st.text_input("操作人 *", placeholder="请输入您的姓名")

    # 需审批的流转：强制填写审批人
    approver = None
    if selected["requires_approval"]:
        approver = st.text_input(
            "审批人 *（必填）",
            placeholder="请输入审批人姓名",
        )

    comment = st.text_area("变更理由 *（必填）", placeholder="请说明变更原因", height=80)
    deliverable = st.text_input("交付物", placeholder="可选，如：立项批复、验收报告等")

    # 提交按钮
    if st.button("✅ 确认变更状态", type="primary"):
        # 严格校验
        errors = []
        if not operator.strip():
            errors.append("操作人不能为空")
        if not comment.strip():
            errors.append("变更理由不能为空")
        if selected["requires_approval"] and not (approver and approver.strip()):
            errors.append("此流转需要审批，审批人不能为空")

        if errors:
            for err in errors:
                st.error(err)
        else:
            result = transition_project(
                project_id=project["id"],
                to_status=selected["to_status"],
                operator=operator.strip(),
                approver=approver.strip() if approver else None,
                comment=comment.strip(),
                deliverable=deliverable.strip(),
            )
            if result["success"]:
                st.success(result["message"])
                st.rerun()
            else:
                st.error(result["message"])


# ============================================================
# 批量导入页面
# ============================================================
def render_import():
    """渲染批量导入页面"""

    st.markdown("## 📥 批量导入历史项目")

    # 下载模板按钮
    st.markdown("### 第一步：下载导入模板")
    st.markdown("请先下载标准模板，按模板格式填写数据后上传。")

    template_bytes = _generate_import_template()
    st.download_button(
        label="📥 下载导入模板（Excel）",
        data=template_bytes,
        file_name="PMO项目导入模板.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("---")

    # 上传文件
    st.markdown("### 第二步：上传数据文件")
    uploaded_file = st.file_uploader(
        "选择 Excel 或 CSV 文件",
        type=["xlsx", "xls", "csv"],
        help="支持 .xlsx / .xls / .csv 格式",
    )

    if not uploaded_file:
        # 返回按钮
        if st.button("← 返回列表"):
            go_list()
        return

    # 读取上传文件
    try:
        if uploaded_file.name.endswith(".csv"):
            df = pd.read_csv(uploaded_file, dtype=str)
        else:
            df = pd.read_excel(uploaded_file, dtype=str)
    except Exception as e:
        st.error("文件读取失败: " + str(e))
        if st.button("← 返回列表"):
            go_list()
        return

    # 替换 NaN 为空字符串
    df = df.fillna("")

    st.markdown("### 第三步：数据预览与字段映射")
    st.markdown("文件共 **" + str(len(df)) + "** 行数据")

    # 字段映射
    # 数据库字段（已移除 priority、planned_start_date、planned_end_date）
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
        "actual_start_date": "实际开始日期",
        "actual_end_date": "实际结束日期",
    }

    # 自动匹配列名
    file_columns = df.columns.tolist()
    mapping = {}

    st.markdown("**字段映射（选择文件中对应的列）：**")

    # 使用 columns 布局映射
    map_cols = st.columns(3)
    for i, (db_field, cn_name) in enumerate(db_fields.items()):
        col = map_cols[i % 3]
        with col:
            # 尝试自动匹配
            default_idx = 0
            for j, fc in enumerate(file_columns):
                if fc.strip() == cn_name or fc.strip().lower() == db_field.lower():
                    default_idx = j + 1
                    break

            options = ["（不映射）"] + file_columns
            selected = st.selectbox(
                cn_name,
                options=options,
                index=default_idx,
                key="map_" + db_field,
            )
            if selected != "（不映射）":
                mapping[db_field] = selected

    # 预览映射后的数据
    if mapping:
        st.markdown("#### 数据预览（前5行）")
        preview_data = []
        for _, row in df.head(5).iterrows():
            record = {}
            for db_field, col_name in mapping.items():
                record[db_field] = str(row.get(col_name, ""))
            preview_data.append(record)
        st.dataframe(pd.DataFrame(preview_data), use_container_width=True, hide_index=True)

    # 确认导入
    st.markdown("---")
    st.markdown("### 第四步：确认导入")

    operator = st.text_input("操作人", placeholder="请输入您的姓名", key="import_operator")

    col_import1, col_import2 = st.columns(2)
    with col_import1:
        import_btn = st.button("✅ 确认导入", type="primary", use_container_width=True)
    with col_import2:
        if st.button("← 返回列表", use_container_width=True):
            go_list()

    if import_btn:
        if not operator.strip():
            st.error("请填写操作人")
        elif not mapping:
            st.error("请至少映射一个字段")
        elif "name" not in mapping:
            st.error("必须映射「项目名称」字段")
        else:
            # 构建导入数据
            records = []
            for _, row in df.iterrows():
                record = {}
                for db_field, col_name in mapping.items():
                    val = str(row.get(col_name, ""))
                    record[db_field] = val if val and val != "nan" else ""
                records.append(record)

            # 执行批量导入
            with st.spinner("正在导入..."):
                result = batch_create_projects(records, operator=operator.strip())

            # 显示导入结果
            st.markdown("### 导入结果")
            res_col1, res_col2, res_col3 = st.columns(3)
            with res_col1:
                st.metric("总数", result["total"])
            with res_col2:
                st.metric("成功", result["success"])
            with res_col3:
                st.metric("失败", result["failed"])

            if result["errors"]:
                st.markdown("#### 错误详情")
                for err in result["errors"]:
                    st.error("第" + str(err["row"]) + "行 [" + err["name"] + "]: " + err["error"])

            if result["success"] > 0:
                st.success("成功导入 " + str(result["success"]) + " 个项目！")

            # 显示导入后按钮
            if st.button("← 返回列表查看"):
                go_list()


# ============================================================
# 工作流管理页面
# ============================================================
def render_workflow():
    """渲染工作流管理页面"""

    st.markdown("## 🔄 工作流管理")

    tab_diagram, tab_statuses, tab_rules = st.tabs([
        "📊 流转图", "📋 状态定义", "📐 流转规则",
    ])

    # ==== Tab1: 流转图 ====
    with tab_diagram:
        try:
            mermaid_code = generate_mermaid_diagram()
            st.markdown("### 项目全生命周期状态流转图")
            st.markdown(
                '<div style="background:#f9fafb; padding:16px; border-radius:8px;">',
                unsafe_allow_html=True,
            )
            st.mermaid(mermaid_code)
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("**图例说明：**")
            st.markdown("- `<<terminal>>` 标记的为终态（已关闭、已终止）")
            st.markdown("- 标注 `[需审批]` 的流转需要指定审批人才能执行")
            st.markdown("- 标注 `[需审批]` 以外的流转为直接操作")
        except Exception as e:
            st.error("流转图加载失败: " + str(e))

    # ==== Tab2: 状态定义 ====
    with tab_statuses:
        try:
            statuses = get_all_statuses()
            for s in statuses:
                is_term = " [终态]" if s["is_terminal"] else ""
                header = (
                    str(s["sort_order"]) + ". "
                    + s["status_name"] + " (" + s["status_code"] + ")"
                    + is_term
                )
                with st.expander(header):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**PMO定义:** " + (s.get("description") or "-"))
                        st.markdown("**准入条件:** " + (s.get("entry_condition") or "-"))
                        st.markdown("**退出条件:** " + (s.get("exit_condition") or "-"))
                    with col2:
                        st.markdown("**责任人:** " + (s.get("responsible_role") or "-"))
                        st.markdown("**关键交付物:** " + (s.get("key_deliverable") or "-"))
        except Exception as e:
            st.error("状态定义加载失败: " + str(e))

    # ==== Tab3: 流转规则 ====
    with tab_rules:
        try:
            rules = get_all_transition_rules()
            status_map = _get_status_map()

            rows = []
            for r in rules:
                from_name = status_map.get(r["from_status"], r["from_status"])
                to_name = status_map.get(r["to_status"], r["to_status"])
                approval = "是 (" + str(r.get("approver_role") or "") + ")" if r["requires_approval"] else "否"
                rows.append({
                    "从": from_name,
                    "→": "→",
                    "到": to_name,
                    "动作": r["action_name"],
                    "需审批": approval,
                    "必要交付物": r.get("required_deliverable") or "-",
                })

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # 统计
            approval_count = sum(1 for r in rules if r["requires_approval"])
            st.markdown("---")
            st.markdown(
                "共 **" + str(len(rules)) + "** 条流转规则 | "
                "需审批: **" + str(approval_count) + "** 条 | "
                "直接操作: **" + str(len(rules) - approval_count) + "** 条"
            )
        except Exception as e:
            st.error("流转规则加载失败: " + str(e))

    # 返回按钮
    st.markdown("---")
    if st.button("← 返回列表"):
        go_list()


# ============================================================
# 侧边栏导航
# ============================================================
with st.sidebar:
    st.markdown("### 📋 PMO项目管理系统")
    st.markdown("---")

    if st.button("🏠 项目列表", use_container_width=True):
        go_list()
    if st.button("➕ 新增项目", use_container_width=True):
        go_create()
    if st.button("📥 批量导入", use_container_width=True):
        go_import()
    if st.button("🔄 工作流管理", use_container_width=True):
        go_workflow()

    st.markdown("---")
    st.markdown(
        '<div style="color:#9ca3af; font-size:11px;">'
        'PMO项目管理系统 v1.3<br>'
        '11个状态 · 34条流转规则<br>'
        '29条需审批 · 5条直接操作'
        '</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# 主路由：根据 session_state 决定渲染哪个视图
# ============================================================
view = st.session_state.view

if view == "list":
    render_project_list()
elif view == "create":
    render_create_project()
elif view == "detail":
    render_project_detail()
elif view == "import":
    render_import()
elif view == "workflow":
    render_workflow()
else:
    render_project_list()
