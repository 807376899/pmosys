# Phase 3 年度资金与正式分配定向验证

- 日期/运行标识：2026-09-17 / `PH3-ANNUAL-PLAN-20260917`
- 需求与验收：REQ-FUND-001@v4、REQ-FUND-002@v2、REQ-FUND-003@v2、REQ-GOV-003@v4、REQ-GOV-004@v3；AC-003、AC-026、AC-027、AC-028、AC-029
- 代码状态：工作树包含未提交改动；本记录只说明本次 Phase 3 的定向证据，不将其外推为完整回归。

| 验收项 | API | Browser | 汇总 | 证据与观察 |
| --- | --- | --- | --- | --- |
| AC-026 年度资金安排与推进盘子 | PASS | NOT_RUN | NOT_RUN | `backend/tests/test_annual_budget_plans.py::test_annual_budget_plan_derives_carryovers_and_saves_candidate_amounts_atomically` 验证续建自动出现、候选统一保存、金额默认/覆盖、计划总额及原子拒绝；资金安排默认折叠的浏览器路径待执行。 |
| AC-027 资金号与项目多对多分配 | PASS | NOT_RUN | NOT_RUN | `backend/tests/test_funding.py::test_project_funding_allocations_are_many_to_many_and_warn_without_blocking` 验证项目→多个资金号、资金号→多个项目、超额警告及项目投影；年度视图折叠入口浏览器路径待执行。 |
| AC-028 正式分配 Excel 回填 | PASS | NOT_RUN | NOT_RUN | `backend/tests/test_annual_budget_plans.py::test_financial_import_rejects_projects_outside_saved_annual_plan` 验证计划外项目行级拒绝；既有 `test_funding.py::test_funding_import_creates_cross_year_source_and_updates_existing_pair` 验证多对多回填。浏览器上传/确认待执行。 |
| AC-003 / AC-029 年度推进与年度预算计划 | PASS | NOT_RUN | NOT_RUN | `backend/tests/test_annual_budget_plans.py` 的 6 项定向用例覆盖跨年续建、当年新增不被重分为续建、零续建金额不计统计、候选默认金额、确认不重复建周期，以及取消/暂缓/恢复/特批/补充纳入的原子拒绝。确认弹窗、整行选择、Stage卡带草案离开和五类操作台路径待浏览器执行。 |

## 实际执行命令

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_funding.py backend\tests\test_pmo_operations.py backend\tests\test_projects_crud.py -q
.\.venv\Scripts\python.exe -m pytest backend\tests\test_advancement_drafts.py -q
\.venv\Scripts\python.exe -m pytest backend\tests\test_annual_budget_plans.py -q
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe scripts\check_docs_governance.py --root .
```

结果：此前年度计划、草案与资金分配定向测试 `12 passed`；本次年度计划收敛追加运行 `backend/tests/test_annual_budget_plans.py` 为 `6 passed`，前端生产构建与文档结构检查成功。浏览器已只读确认第三视图、年度分组、候选默认有效预算、折叠资金安排及确认入口；为保护现有用户数据，未执行确认、取消推进、暂缓/恢复/特批等写路径。完整 Phase 3 浏览器写操作、导入上传和跨视图回显仍为 `NOT_RUN`。

## 2026-09-18 证据追加：年度分类与详情进度投影

- 对应当前规则：REQ-GOV-003@v5、REQ-GOV-004@v4、REQ-FUND-001@v5、REQ-UI-006@v6；AC-003、AC-022、AC-026、AC-029。
- 定向命令：`\.venv\Scripts\python.exe -m pytest backend\tests\test_annual_budget_plans.py backend\tests\test_projects_crud.py -q`，结果 `27 passed`；`npm.cmd --prefix frontend run build`；`\.venv\Scripts\python.exe scripts\check_docs_governance.py --root .`。
- API 证据新增：当年确认项目仍为本年新增且下一年才成为续建；零本年新增安排成员仍保留但不计项目/分类统计；详情投影返回草案或确认计划年份，以及仅立项入库、完成、废弃三类 Stage 事件。
- Browser：`NOT_RUN`（写路径未执行）。已只读验证 2026 年年度预算安排：项目库—未实施与未立项候选均带出当前有效预算；并打开未立项与已完成项目详情，确认“计划推进年份”显示“未纳入年度计划”或实际推进年度，且已完成项目在事项区以“项目完成”单行事件呈现。为保护现有用户数据，未执行确认、取消、金额保存、切换年度后的分类持久化或事项间锚定的写路径；这些浏览器用例仍待独立回归。

## 2026-09-18 证据追加：资金代码导入字段与待补录分配

- 对应当前规则：REQ-FUND-002@v3、REQ-FUND-003@v3；AC-027、AC-028。
- API：`\.venv\Scripts\python.exe -m pytest backend\tests\test_funding.py backend\tests\test_annual_budget_plans.py -q`，结果 `12 passed`。新增 `test_funding_import_keeps_project_source_link_when_allocation_amount_is_blank` 覆盖中文模板列、资金名称/负责人、资金金额与可空分配金额、项目×资金代码关联、来源投影及刷新后读取。
- Build：`npm.cmd --prefix frontend run build` 成功；Document：`\.venv\Scripts\python.exe scripts\check_docs_governance.py --root .` 成功。
- Browser：`NOT_RUN`。浏览器控制会话无法载入请求头策略，未执行导出、上传与确认写路径；这不影响 API 证据，但 AC-027、AC-028 的整体状态仍为 `NOT_RUN`，待独立浏览器回归。
