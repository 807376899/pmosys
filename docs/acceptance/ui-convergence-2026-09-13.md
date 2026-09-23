# 阶段跟踪与快速办理 UI 收敛：定向验证记录

| 字段 | 记录 |
| --- | --- |
| 日期/运行标识 | 2026-09-13 / UI-CONVERGENCE-20260913 |
| 需求/验收版本 | REQ-WI-003@v2、REQ-WI-004@v2、REQ-EC-001@v2、REQ-UI-004@v2、REQ-UI-005@v2、REQ-UI-006@v2、REQ-UI-007@v3；AC-009、AC-010、AC-012、AC-020、AC-021、AC-022、AC-023 |
| 代码版本 | `ea49378` + 当前未提交本轮实现；工作树含此前文档治理改动与本轮源代码改动 |
| 环境 | Windows 本机 FastAPI `127.0.0.1:8000`、Vite `localhost:5173`、Edge 真实浏览器 |

## 实际执行证据

| 范围 | 验证层 | 结果 | 观察/证据 |
| --- | --- | --- | --- |
| 首次开始日期、完成日期、完成事实更正与里程碑同步 | API | PASS | `backend/tests/test_work_items.py` 与 `backend/tests/test_external_constraints.py` 定向执行 `39 passed`；覆盖单项、快速、批量首次开始，重开不覆盖，完成记录日期，更正与审计。 |
| 约束首次办理日期与阶段投影 | API | PASS | 同一组定向测试覆盖初始办理中、开始办理、重复开始与列表投影。 |
| 需求/决策/验收引用结构 | Document | PASS | `scripts/check_docs_governance.py --root .` 成功；该检查仅验证结构和引用，不证明自然语言无冲突。 |
| 前端类型与生产构建 | Build | PASS | `npm.cmd --prefix frontend run build` 成功。 |
| 超宽版心与阶段跟踪单元格 | Browser | PASS（定向） | Edge 工作台实测：`.hero` 与 `.workspace` 均为 `1720px`、左边界均为 `331px`；阶段表头只显示业务名称并有无文字来源符号，事项/约束单元格均显示状态和事实日期/缺失提示。 |
| 已完成事项快速办理 | Browser | PASS（定向） | 从阶段跟踪点击已完成 `PMO 审核` 后，右侧显示“已完成”、完成日期、结果、说明、里程碑以及“修改事项 / 重开事项 / 补充备注”，未显示待办理设置表单。 |
| 超宽屏详情页版心 | Browser | PASS（定向） | Edge 实测 `2106×1269`：`.detail-hero`、`.detail-layout` 均为 `1720px`，左右边界均为 `186px / 1906px`；主内容与侧栏相邻，页面 `scrollWidth=2091`，未超过视口。 |
| Dashboard 提示容器 | Browser | NOT_RUN | 已在实际 Dashboard 源码路径中将裸 `.notice` 改为 `.dashboard-notices`；本次未通过真实成功/失败写操作触发展示，不将静态检查或构建替代该浏览器用例。 |

## 未执行的阶段性回归

- AC-009、AC-010、AC-012、AC-020、AC-021、AC-022、AC-023 的完整 API + Browser 矩阵仍为 `NOT_RUN`：本次只执行直接受影响的定向测试与单一真实浏览器入口，没有执行全部历史/视口组合。
- 未在真实浏览器中提交完成事实更正、约束开始办理或全部响应式视口；这些需在 Phase 收尾或独立回归窗口执行。
