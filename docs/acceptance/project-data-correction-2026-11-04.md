# 2026-11-04 项目资料统一更正定向验证

## 运行信息

| 字段 | 记录 |
| --- | --- |
| 日期/运行标识 | 2026-11-04 / `project-data-correction-20261104` |
| 需求与验收 | REQ-PRJ-001@v6、REQ-GOV-002@v6、REQ-GOV-003@v7、REQ-UI-006@v14；AC-002、AC-004、AC-022、REG-PRJ-001 |
| 工作树 | `codex/pmo-dashboard-simplify`；记录时包含本次实现改动，以及未纳入本次提交的既有 AGENTS.md、frontend/index.html 和治理资料改动 |
| 环境 | Windows；Python `.venv`；隔离临时 SQLite 库 `pmosys-project-correction-browser.db`；Vite 本地开发服务 `127.0.0.1:5173` |

## 已执行证据

| 层级 | 操作与观察 | 结果 |
| --- | --- | --- |
| API | `backend/tests/test_project_corrections.py` 覆盖五种 Stage、历史编号、无损预算、已完成推进周期与年度成员迁移，以及缺完成日期的原子拒绝；与历史导入、年度计划及项目 CRUD 测试合并执行。 | PASS：`42 passed` |
| 构建 | `npm.cmd --prefix frontend run build`。 | PASS：生产构建完成。 |
| 文档 | `scripts/check_docs_governance.py` 与 `tests/test_docs_governance.py -q`。 | PASS：`26 passed`。 |
| Browser | 隔离项目详情打开“编辑项目资料”，将编号改为 `SW20250001`、状态改为已完成、推进年度填写 `2025`、完成时间填写 `2026-02` 后保存；页面即时显示已完成、实施年份 `2025` 和完成时间 `2026-02`，刷新后仍一致。随后清空推进年度保存，字段错误出现且编辑草稿未丢失。 | PASS：正常写入、刷新持久化与前端必填失败恢复已验证。 |

## 覆盖边界与待办

- 已覆盖单项目详情更正、推进年度同步、年度成员迁移、历史编号、无损金额、成功回显与失败草稿保留。
- 未执行所有五个 Stage 的浏览器矩阵、导出文件逐字段核对，以及含外部约束预算来源、多历史周期、合同和办理活动的人工浏览器回归；这些属于 `REG-PRJ-001` 的后续完整回归，当前为 NOT_RUN，不以本次定向结果替代。

## 总体结果

本次已执行层级均为 PASS；完整跨场景回归仍为 NOT_RUN。
