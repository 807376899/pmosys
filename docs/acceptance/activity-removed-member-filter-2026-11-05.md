# 办理活动移出成员筛选定向验证（2026-11-05）

- 需求/验收：`REQ-ACTIVITY-001@v3`、`AC-032`。
- 代码版本：`55139b6` 基础上的未提交定向修复；保留既有无关 dirty 文件。
- 环境：本机 Python 3.11 / FastAPI / SQLite 测试数据、Vite 本地工作台；浏览器正常入口。

## 执行结果

| 层级 | 结果 | 证据 |
| --- | --- | --- |
| API | PASS | `backend/tests/test_work_item_activities.py` 的移出成员回归覆盖：返回成员历史保留 `removed`，`member_count` 为 1、结果数为 0，移出项目事项投影的 `activity_summaries` 为空；定向套件 `6 passed`。 |
| Build | PASS | `npm.cmd --prefix frontend run build` 完成 TypeScript 检查与 Vite 生产构建。 |
| Document | PASS | `scripts/check_docs_governance.py` 与 `tests/test_docs_governance.py`（`26 passed`）通过。 |
| Browser | PASS | 创建两个同名事项成员的“浏览器成员移出验证活动”，移出其中一项后：阶段单元格仅保留项目显示活动；点击活动及从“办理活动记录”重开均只显示保留项目，右侧显示“活动成员 1 个”；切换“查看全部项目”时，移出项目不显示该活动按钮且未被默认选中。 |

## 结论

移出成员的历史、原因和审计仍在活动响应中保留；日常活动上下文、成员数量、结果数量、默认选择和项目事项活动摘要均只采用 `active` 成员。

## 回归说明

执行完整 `backend/tests` 套件时，在第 18 项遇到 `test_contract_number_is_required_even_before_performance` 的测试隔离/顺序异常：`project_types` 表不存在。该测试单独执行通过；本轮未修改合同、项目分类或迁移代码，因此不将该异常归因为本次办理活动修复。完整套件结果保留为 `FAIL`，待独立回归窗口处理；本轮所需 API、Build、Document、Browser 证据如上。
