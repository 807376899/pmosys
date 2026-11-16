# 年度计划列与显示列控件定向验证（2026-11-16）

## 范围与版本

- 需求：`REQ-FUND-001@v6`、`REQ-UI-003@v23`、`REQ-UI-004@v17`、`REQ-UI-007@v9`
- 验收：`AC-019`、`AC-020`、`AC-023`、`AC-026`、`REG-UI-001`
- 工作树：仅记录本次年度计划采购类型、列宽、显示列控件和状态卡片接合实现；用户既有 `AGENTS.md`、Figma 入口、历史文档草稿及测试构建目录未纳入本次提交。

## 结果

| 层级 | 状态 | 步骤与观察 | 证据 |
| --- | --- | --- | --- |
| 年度计划 API 定向测试 | PASS | 年度计划投影返回项目采购属性，前端可据此表达软件的货物/服务/混合及场所默认货物。 | `python -m pytest backend/tests/test_annual_budget_plans.py -q`，10 passed |
| 前端定向测试 | PASS | 年度计划采购类型展示纯函数、总览/阶段/年度列宽序列化与最小宽度均通过。 | `npm.cmd --prefix frontend run test:annual-plan`（2 passed）；`npm.cmd --prefix frontend run test:columns`（7 passed） |
| 前端构建 | PASS | TypeScript 检查和生产打包完成。 | `npm.cmd --prefix frontend run build` |
| 文档治理检查 | PASS | 当前需求、决策、验收清单和验收记录的结构及引用检查通过。 | `python scripts/check_docs_governance.py`；`python -m pytest tests/test_docs_governance.py -q`，26 passed |
| 浏览器定向验证 | PASS（已覆盖部分） | 本机工作台总览显示列弹层出现全选/取消全选控件；全选立即显示所有可用基础列，取消后立即移除，点击状态卡外部区域关闭弹层。年度预算安排显示“分类 / 采购类型”、软件服务项目和场所货物项目，表头提供全部列的拖拽分隔线与恢复默认列宽。浏览器读取到激活卡片所在 group band 底边与项目表顶边一致，激活卡片伪元素延伸 24px 形成连续视觉连接。 | 本机 `127.0.0.1:5173`，2026-11-16 可访问性树及截图 |
| 完整响应式矩阵 | NOT_RUN | 尚未逐一执行 1440×900、1100×768、900×768、768×1024、600×900 的所有拖拽与视觉路径。 | 留待阶段性回归 |

## 结论

本轮定向 API、前端测试、构建及本地浏览器主路径已完成。完整多视口矩阵仍未执行，因此关联验收与整体回归不得据此整体标为 `PASS`。
