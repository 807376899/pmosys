# 2026-09-14 项目列表年份列与排序定向验证

| 字段 | 记录 |
| --- | --- |
| 需求/验收版本 | REQ-PRJ-003@v5、REQ-UI-003@v3；AC-006、AC-019 |
| 代码版本 | `ea49378`，工作树含未提交的用户与本次改动 |
| 自动化环境 | FastAPI TestClient、临时 SQLite 数据库 |
| API 结果 | PASS：`backend/tests/test_projects_crud.py`、`backend/tests/test_exports.py` 共 19 项通过；覆盖学院→实施年份→项目编号、实施/完成年份→学院→项目编号及导出回归。 |
| 构建结果 | PASS：`npm.cmd --prefix frontend run build`。 |
| Browser 结果 | BLOCKED：当前会话没有可用的桌面浏览器自动化连接；需恢复后在推进中与已完成视图确认独立年份列、已完成隐藏推进情况、状态色和两类年份排序。 |
| 总体结果 | BLOCKED：所需 Browser 层尚未执行；API 与构建结果不替代浏览器验收。 |
