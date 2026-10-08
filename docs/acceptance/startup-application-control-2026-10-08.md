# 2026-10-08 Windows 应用控制策略启动修复

- 运行标识：ENV-STARTUP-20261008；日期：2026-10-08。
- 范围：修复本机后端启动失败；不改变业务需求、数据库或前端。
- 环境：Windows PowerShell、Python 3.11.9、本机 `.venv`、SQLite WAL；工作树已有未提交业务与 Figma 相关修改，均未重置或覆盖。

## 根因与处理

启动日志显示 `pandas._libs.join` 无法加载。Windows Code Integrity 日志记录事件 3033/3077：该 `.pyd` 未满足企业签名策略。因此这不是缺包、版本落后或 `pip check` 能发现的依赖关系错误，重复升级/安装 pandas 也不能解决。

项目仅将 pandas 用于项目导入、项目导出和正式资金分配 Excel 的读写。现改用已声明的 `openpyxl`、`xlrd` 和 Python 标准库 CSV：保留 `.xlsx`、`.xls`、CSV 导入以及现有工作簿字段/工作表语义，移除 pandas 运行时与测试依赖。`run.ps1` 在依赖同步后导入 `backend.app.main`，导入失败时不启动 Uvicorn，并保留原始异常以便定位策略或环境问题。

同时修正历史实施补录中“明确清除真实 0 预算”的无损金额比较：字符串 `"0"` 与旧 REAL `0` 均可由用户明确清除；不自动清除非零或未授权预算。

## 执行结果与证据

| 层/用例 | 状态 | 命令与观察 |
| --- | --- | --- |
| Root cause | PASS | 直接导入 pandas 重现 DLL 阻止；Code Integrity 事件 3033/3077 指向 `pandas/_libs/join.cp311-win_amd64.pyd`。 |
| Script | PASS | ` .\.venv\Scripts\python.exe -m pytest tests\test_run_script.py -q`：3 passed。覆盖安装失败、运行时导入失败均不启动 Uvicorn。 |
| API/Excel | PASS | ` .\.venv\Scripts\python.exe -m pytest backend\tests\test_imports.py backend\tests\test_exports.py backend\tests\test_funding.py backend\tests\test_annual_budget_plans.py tests\test_run_script.py -q`：28 passed。覆盖项目导入导出、资金模板/导入、年度计划和启动保护。 |
| Runtime | PASS | 实际运行 ` .\run.ps1`：默认 WatchFiles 热重载、API 导入、数据库初始化均完成；`http://127.0.0.1:8000/openapi.json` 返回 200。随后停止本次验证进程。 |
| Browser/完整回归 | NOT_RUN | 本轮无界面修改；未执行浏览器路径和阶段完整回归。 |

FastAPI 生命周期与 TestClient 的现有弃用提示仍存在，但不影响本轮启动或定向测试；未为此引入额外依赖或框架迁移。
