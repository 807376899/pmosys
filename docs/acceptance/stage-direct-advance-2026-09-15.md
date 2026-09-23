# 2026-09-15 Stage 直接推进定向验证

| 字段 | 记录 |
| --- | --- |
| 日期/运行标识 | 2026-09-15 / REG-STAGE-20260915 |
| 需求/验收版本 | REQ-GOV-002@v5、REQ-BULK-001@v4、REQ-UI-002@v2、REQ-UI-003@v6；AC-002、AC-015、AC-018、AC-019 |
| 代码版本 | `ea49378`，工作树 dirty（本次及先前未提交改动共存） |
| 环境与对象 | pytest 临时 SQLite；本机 Vite 浏览器使用既有用户数据库，仅执行无写入详情查看、Stage 入口与阻塞路径。 |

| 范围 | API | Browser | Document | 汇总 | 证据/说明 |
| --- | --- | --- | --- | --- | --- |
| 立项直接推进与终止事项 | PASS | NOT_RUN | — | NOT_RUN | `test_direct_stage_establishment_allows_only_terminal_work_items_and_records_document` 通过：零/完成/取消/跳过/不适用事项不阻塞，统一立项文件号写入详情和状态历史。真实浏览器成功写入未执行，避免改动用户数据。 |
| 阻塞原因与原子回滚 | PASS | PASS | — | PASS | `test_direct_stage_establishment_rejects_unfinished_item_atomically` 通过；浏览器选择含未终止事项项目并填写文号后显示具体事项原因，选中对象与输入保留。 |
| 完成项目与推进周期 | PASS | NOT_RUN | — | NOT_RUN | `test_direct_stage_completion_closes_active_cycle_and_sets_completion_date` 通过：Stage、完成日期及 active 周期同步完成。真实浏览器成功写入未执行，避免改动用户数据。 |
| 工作台入口与立项文件展示 | — | PASS | PASS | PASS | 浏览器确认操作台显示“Stage 推进”、立项文件号输入和例外特批折叠入口，不显示普通预览或“未命中共同状态”；项目表新增“立项文件”列，详情概况显示“立项文件号”。文档结构检查通过。 |

实际执行命令：

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_transitions_batch.py backend\tests\test_work_items.py -q
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe scripts\check_docs_governance.py --root .
```

结果：后端定向模块 `32 passed`；前端生产构建成功；文档结构检查通过。真实浏览器未对用户现有数据执行成功写入链路，故涉及成功写入的 Browser 层保持 `NOT_RUN`；完整 Phase 回归留待独立回归窗口。
