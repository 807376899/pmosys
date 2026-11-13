# 2026-11-13 新增项目与项目概括快速办理定向验证

## 运行信息

| 项目 | 记录 |
| --- | --- |
| 日期 / 运行标识 | 2026-11-13 / `project-summary-quick-edit` |
| 需求与验收 | `REQ-PRJ-001@v7`、`REQ-PRJ-003@v9`、`REQ-UI-003@v22`、`REQ-UI-005@v17`；AC-004、AC-006、AC-019、AC-021、REG-UI-001 |
| 代码版本 | 提交前工作树；仅记录本轮项目描述接口、工作台表单/概括入口与关联文档改动，另有既存未提交文件未纳入本次范围 |
| 环境 | Windows 本机；FastAPI `127.0.0.1:8000`；Vite `127.0.0.1:5173`；浏览器本地工作台 |

## 执行与证据

| 层级 | 步骤与观察 | 结果 |
| --- | --- | --- |
| API | 运行 `backend/tests/test_projects_crud.py::test_project_description_quick_update_needs_no_reason_and_keeps_other_facts`。更新与清空描述均成功；预算、Stage、最新动态保持不变；审计事件为 `PROJECT_DESCRIPTION_UPDATED`，含前后描述且理由为空。 | PASS |
| Frontend | 运行 `npm.cmd --prefix frontend run test:columns` 与 `npm.cmd --prefix frontend run build`；列配置定向测试 6/6 通过，TypeScript 与 Vite 生产构建通过。 | PASS |
| Document | 运行 `scripts/check_docs_governance.py`；结构检查通过。 | PASS |
| Browser | 新增“概括快速办理浏览器验证项目”：学院输入“测试学院”、负责人输入“验证负责人”、项目说明输入“原始项目概括”；表单显示统一字段标题与输入控件。启用未立项总览的项目概括列后，点击该项目描述打开右侧“修改项目概括”，确认没有选中项目摘要；保存“更新后的项目概括”后得到成功提示。刷新工作台并再次打开相同入口，文本仍为“更新后的项目概括”。 | PASS |

## 边界与待办

- 本次只执行定向浏览器路径，不替代四个 Stage、窄屏和完整回归矩阵；这些场景保持 `NOT_RUN`。
- 浏览器路径新建的是本机测试记录 `SY20260020`，未清除或修改既有项目数据。
