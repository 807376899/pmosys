# 2026-09-14 历史导入与完成项目定向验证

| 字段 | 记录 |
| --- | --- |
| 需求/验收版本 | REQ-GOV-002@v4、REQ-PRJ-001@v4、REQ-PRJ-003@v4、REQ-UI-006@v3；AC-002、AC-004、AC-006、AC-022 |
| 代码版本 | `ea49378`，工作树含未提交的用户与本次改动 |
| 自动化环境 | FastAPI TestClient、临时 SQLite 数据库 |
| API 结果（原） | PASS：`backend/tests/test_imports.py`、`backend/tests/test_projects_crud.py` 共 22 项通过；覆盖完成周期投影、跨年度完成时间、历史编号、预算空值、批量补录与实施年份排序。该次记录只覆盖历史编号预览，未覆盖确认写入。 |
| 本次 API 结果 | PASS：`backend/tests/test_imports.py` 共 10 项通过；新增“`SY20200001` + 空编号确认写入”“确认重校验零写入”和“预览后数据库编号冲突”覆盖。 |
| 本次 Browser 结果 | NOT_RUN：真实库刚按用户要求清空，未为本次验证写入临时项目。需使用隔离浏览器数据库补充 AC-004 的上传、确认失败行级反馈、成功列表回显与刷新持久化。 |
| 构建结果 | PASS：`npm.cmd --prefix frontend run build`。 |
| Browser 结果 | BLOCKED：本机 Computer Use 原生管道无法连接（系统找不到指定文件），无法执行真实浏览器的补录、详情编辑、刷新持久化和模板提示验证。解除条件：恢复桌面浏览器自动化后，使用隔离项目完成 AC-002/004/006/022 的 Browser 层。 |
| 总体结果 | BLOCKED：所需 Browser 层尚未执行；API 与构建结果不替代浏览器验收。 |
