from __future__ import annotations

import pandas as pd
import streamlit as st

from lib.database import batch_create_projects
from utils.exports import generate_import_template
from utils.session import current_operator, go_dashboard


def render_import() -> None:
    """渲染批量导入页面。"""
    st.markdown("## 📥 批量导入历史项目")
    st.caption("先下载模板，再上传 Excel / CSV，完成字段映射后批量导入。")

    st.download_button(
        label="📥 下载导入模板（Excel）",
        data=generate_import_template(),
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
    mapping: dict[str, str] = {}

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
    operator = st.text_input("操作人", value=current_operator(), key="import_operator")

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
                        st.error("第 " + str(item["row"]) + " 行 [" + item["name"] + "]：" + item["error"])

            if result["success"] > 0:
                st.success("成功导入 " + str(result["success"]) + " 个项目。")
