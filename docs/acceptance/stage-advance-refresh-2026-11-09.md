# 2026-11-09 普通 Stage 推进刷新与选择状态定向验证

- 需求/验收：`REQ-UI-002@v5`、`REQ-UI-003@v21`、`REQ-UI-007@v8`；`AC-018`、`AC-019`、`AC-023`、`REG-UI-001`。
- 代码版本：待本次提交；开始时工作树含既有无关 `AGENTS.md`、`frontend/index.html` 与文档/测试产物改动，未纳入本次范围。
- 环境：Windows 本机，Python 3.11 虚拟环境，FastAPI `127.0.0.1:8000`，Vite `127.0.0.1:5173`，ChatGPT in-app browser。

| 层级 | 结果 | 步骤与观察 | 证据 |
| --- | --- | --- | --- |
| 前端定向 | PASS | 给加载序号与结果集变化分别新增回归断言；旧请求序号不等于最新序号时不可写入，Stage/筛选结果集键变化时必须清空普通选择。 | `npm.cmd --prefix frontend run test:rail`：5 passed。 |
| 后端 API | PASS | 执行既有批量 Stage 推进回归，覆盖零事项/全部终止事项可直接完成、未终止事项阻塞与 active 周期结束。合同、资金分配和外部约束不作为普通完成门槛。 | `\.venv\Scripts\python.exe -m pytest backend\tests\test_transitions_batch.py -q`：4 passed（11 条第三方弃用 warning）。 |
| 前端构建 | PASS | TypeScript 与生产 Vite 构建成功。 | `npm.cmd --prefix frontend run build`：exit 0。 |
| 浏览器写入与刷新 | PASS | 在“推进中”选择无未终止事项的测试项目“内外贸一体化数字品牌运营决策模拟沙盘软件（SW20260002）”，点击“完成项目”。成功提示后仍停留推进中：项目数由 3 变 2，项目立即消失，状态卡由推进中 3/190 万、已完成 2/62 万变为推进中 2/120 万、已完成 3/132 万。刷新页面后再进入已完成，列表包含该项目。 | 2026-11-09 in-app browser DOM 与截图；API 读取前置证明该项目 6 个事项均 `completed`。 |
| 完整响应式/并发网络浏览器矩阵 | NOT_RUN | 本次完成正常入口写入、持久化及刷新，但未在真实浏览器人为延迟网络请求并逐一覆盖所有目标视口。 | 后续按 `AC-023`、`REG-UI-001` 阶段回归执行。 |

本次浏览器操作改变了现有测试数据：项目 `SW20260002` 已由推进中正常完成，保留其正常状态历史与完成时间；未对数据库执行清空、重置或回滚。
