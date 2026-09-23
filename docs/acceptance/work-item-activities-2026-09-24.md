# 办理活动替代批次：定向验收记录

| 字段 | 记录 |
| --- | --- |
| 日期 | 2026-09-24 |
| 需求与验收 | REQ-ACTIVITY-001@v1；AC-032 |
| 代码状态 | 当前工作树，未提交 |
| 数据环境 | pytest 临时 SQLite；未修改用户 `pmo.db` |

## 已执行证据

- API：` .\.venv\Scripts\python.exe -m pytest backend\tests\test_work_item_activities.py backend\tests\test_pmo_operations.py -q`，13 passed。覆盖创建活动不新增/不改变事项、共享活动进展不写入项目事项进展、成员可登记不同结果、结果不完成事项、全员登记后自动结束。
- Build：`npm.cmd --prefix frontend run build`，通过。
- Document：` .\.venv\Scripts\python.exe scripts\check_docs_governance.py`，通过；仅验证结构和引用，不代表语义或浏览器验收。

## 浏览器与尚未执行

- Browser：NOT_RUN（已做只读入口观察）。在本机 `127.0.0.1:5173` 总览右侧观察到“推进管理”“办理活动”为并列一级入口；打开办理活动后显示独立的年度、状态、事项/项目/活动名称筛选和迁移后的活动记录，未进入推进管理。未执行任何浏览器写入。
- 尚未在真实浏览器逐项完成阶段列新建/加入活动、单元格活动入口、成员管理、活动内批量完成、返回上下文及窄屏滚动写链路。
- 完整回归：NOT_RUN，留待 Phase 收尾或独立回归窗口。
