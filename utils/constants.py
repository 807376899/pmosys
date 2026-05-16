from __future__ import annotations


GROUP_FILTERS = {
    "all": {"label": "全部项目", "statuses": None},
    "pre_establish": {"label": "未立项", "statuses": ["draft", "under_review"]},
    "pool_pending": {"label": "项目库-未实施", "statuses": ["established", "submission_review"]},
    "pool_active": {
        "label": "项目库-实施中",
        "statuses": ["procuring", "implementing", "trial", "accepting", "suspended"],
    },
    "completed": {"label": "已完成", "statuses": ["closed"]},
    "abandoned": {"label": "已废弃", "statuses": ["terminated"]},
}

GROUP_ORDER = [
    "all",
    "pre_establish",
    "pool_pending",
    "pool_active",
    "completed",
    "abandoned",
]

DASHBOARD_FILTER_DEFAULTS = {
    "dashboard_group_filter": "all",
    "dashboard_keyword": "",
    "dashboard_department": "全部",
    "dashboard_detail_status": "全部",
    "dashboard_declaration_year": "全部",
    "dashboard_implementation_year": "全部",
}
