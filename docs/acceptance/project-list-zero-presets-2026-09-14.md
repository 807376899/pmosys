# 2026-09-14 项目列表与零预置定向验证

| 字段 | 记录 |
| --- | --- |
| 日期/运行标识 | 2026-09-14 / REG-PLZP-20260914 |
| 需求/验收版本 | REQ-PRJ-003@v6、REQ-WI-001@v2、REQ-TPL-001@v2、REQ-EC-001@v3、REQ-EC-002@v2、REQ-UI-003@v4、REQ-UI-004@v3、REQ-UI-008@v2；AC-006、AC-007、AC-011、AC-012、AC-013、AC-019、AC-020、AC-024 |
| 代码版本 | `ea49378`，工作树 dirty（本次及先前未提交改动共存） |
| 环境与对象 | pytest 临时 SQLite；本机 Vite 浏览器只读检查使用已运行服务，未向用户数据库写入测试数据。 |

| 范围 | API | Browser | Document | 汇总 | 证据/说明 |
| --- | --- | --- | --- | --- | --- |
| 零预置、显式创建及旧预置归档 | PASS | NOT_RUN | — | NOT_RUN | `test_fresh_database_has_no_system_seeded_templates_or_project_instances`、`test_legacy_system_template_is_archived_when_a_project_instance_references_it` 通过；未重启用户正在使用的后端来对其旧库执行迁移。 |
| 主流程前两项、重点关注及无实例“—” | PASS | NOT_RUN | — | NOT_RUN | `test_work_item_summary_shows_two_main_flow_items_then_every_focus_item` 通过；浏览器仅观察到旧服务的历史实例，不能替代迁移后浏览器验收。 |
| 导入不自动创建事项或约束 | PASS | NOT_RUN | — | NOT_RUN | `test_import_preview_and_commit` 补充并通过导入后两类实例均为空的断言。 |
| 默认排序、年份筛选候选项与最新动态 | PASS | NOT_RUN | PASS | NOT_RUN | `test_default_list_sort_and_year_facet_do_not_depend_on_current_result`、`test_progress_log_updates_latest_activity_but_basic_project_edit_does_not` 通过；浏览器确认列表显示“最新动态”列和默认学院升序请求，但未在隔离数据中完成全部筛选/刷新链路。 |

实际执行命令：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_projects_crud.py backend\tests\test_work_items.py backend\tests\test_external_constraints.py backend\tests\test_imports.py -q
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe scripts\check_docs_governance.py --root .
```

结果：后端定向模块 `70 passed`；前端生产构建成功；文档结构检查通过。完整 Phase 回归、旧库迁移后的浏览器链路、阶段跟踪“会议”无实例可视验收及所有视口回归留待独立回归窗口。
