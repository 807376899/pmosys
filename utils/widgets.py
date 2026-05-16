from __future__ import annotations

from typing import Optional

import streamlit as st


def render_budget_adjustment_inputs(
    *,
    key_prefix: str,
    current_budget: float,
    current_approved_budget: Optional[float],
    enabled: bool,
) -> tuple[bool, Optional[float]]:
    """渲染审核后预算调整输入。"""
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
