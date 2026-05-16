from __future__ import annotations

from typing import Optional

import streamlit as st

from lib.database import get_all_statuses


@st.cache_data(ttl=30)
def get_status_definitions() -> list[dict]:
    """缓存状态定义。"""
    return get_all_statuses()


def get_status_map() -> dict[str, str]:
    """状态码到中文名映射。"""
    return {item["status_code"]: item["status_name"] for item in get_status_definitions()}


def get_status_order_map() -> dict[str, int]:
    """状态码到排序号映射。"""
    return {item["status_code"]: item["sort_order"] for item in get_status_definitions()}


def get_status_name(status_code: str) -> str:
    """获取状态中文名。"""
    return get_status_map().get(status_code, status_code)


def get_status_color(status_code: str) -> str:
    """获取状态颜色。"""
    for item in get_status_definitions():
        if item["status_code"] == status_code:
            return item["color"]
    return "#6B7280"


def status_badge(status_code: str) -> str:
    """渲染状态徽章 HTML。"""
    style = (
        "display:inline-block; padding:3px 10px; border-radius:999px; "
        "color:white; font-size:12px; font-weight:600; "
        "background-color:" + get_status_color(status_code) + ";"
    )
    return '<span style="' + style + '">' + get_status_name(status_code) + "</span>"


def budget_display(value: Optional[float]) -> str:
    """预算展示文本。"""
    if value is None:
        return "-"
    return f"{float(value):,.2f}"
