# 2026-09-24 环境与启动依赖同步检查

- 运行标识：ENV-SYNC-20260924；日期：2026-09-24。
- 代码基准：`a2b3421dab323867a795a9424d9f9b48d66676cd`，dirty 工作树。
- 开始时已有修改：`AGENTS.md`；未跟踪的证据复核、设置审计、治理整改与历史目录均保留。
- 本轮范围：依赖同步、`run.ps1` 安装失败处理、启动说明和启动回归用例。属于环境脚本缺陷，不改变业务 REQ 或 AC 预期；读取当前需求基线、决策日志与验收清单，未发现专门环境 REQ，无业务版本变更。
- 环境：Windows PowerShell；Python 3.11.9，本机安装创建的项目 `.venv`；Node.js v24.16.0；Vite 5.4.21。

## 发现与处理

1. `git log/show` 确认 `f4b099c`（2026-09-23）在 `requirements.txt` 新增 `xlrd>=2.0.1`。本机为 2.0.2，无缺包；其他声明也满足。
2. 原脚本仅导入 fastapi、uvicorn、pandas、openpyxl，遗漏新增包及版本约束，并在 pip 安装失败后继续启动。改为每次执行 `pip install -r requirements.txt`，失败立即停止；不使用 `--upgrade`。
3. 实际执行上述 pip 安装，所有包均 already satisfied，没有升级 Python 包。`pip check` 报告 No broken requirements found。
4. 前端执行 `npm.cmd --prefix frontend ci --ignore-scripts --no-audit --no-fund`，按已有锁文件重装 72 个包；package.json、锁文件和 requirements.txt 均未修改。此次安装禁用生命周期脚本，后续生产构建实际通过。
5. README 更新首次启动和测试机更新说明，明确 Python 仍是最低版本约束，未宣称两机环境完全一致。

## 执行结果与证据

| 层/用例 | 状态 | 命令、观察与证据 |
| --- | --- | --- |
| Script：依赖同步成功/失败 | PASS | `python -m pytest tests/test_run_script.py -q` 对应两个参数场景；修改前均因未调用 pip 失败，修改后两项通过。只替换解释器为测试替身，实际执行脚本分支，确认安装成功才启动、失败非零退出。用例见 `tests/test_run_script.py`。 |
| Runtime：真实启动 | PASS | 实际执行 `powershell -NoProfile -ExecutionPolicy Bypass -File run.ps1 -NoReload -Port <临时端口>`，通过 PMO_DB_PATH 指向临时目录；健康接口返回 `{"status":"ok"}`，随后终止本次进程树并清理临时目录。用户数据库未作为测试目标。 |
| API：健康检查与导入定向检查 | FAIL | `.venv/Scripts/python.exe -m pytest tests/test_run_script.py backend/tests/test_health.py backend/tests/test_imports.py -q`：11 passed、2 failed。启动两项、健康一项通过，导入 8 项通过、2 项失败，详情见下文。 |
| Build | PASS | `npm.cmd --prefix frontend run build`：TypeScript 与 Vite 构建成功，1639 modules transformed。 |
| Document | PASS | `.venv/Scripts/python.exe scripts/check_docs_governance.py` 结构/引用检查通过；不代表业务语义一致或产品验收完成。 |

总体定向验证结果：**FAIL**，由导入模块两项失败决定；不将环境修复通过等同于全部产品验证通过。

## 范围外发现与待办

- `test_import_preview_and_commit`：预览 approved_budget 实际为字符串 `'45'`，旧断言要求数值 `45.0`。需结合当前金额接口约定裁定测试预期；未修改断言以消除失败。
- `test_batch_backfill_completed_history_creates_cycle_and_can_clear_imported_zero_budget`：清理后 budget 实际为 `'0'`，预期 None。服务 `projects.py` 的清理条件仍与数值 0 比较，需进一步核对金额投影与存储清理链。此次只记录，未修复业务代码。
- 测试同时出现 FastAPI on_event、Starlette TestClient 弃用提示；本轮未据此新增依赖或迁移框架接口。
- 新机实际部署：NOT_RUN，当前操作只覆盖这台开发机；新机需同步未提交的脚本修改后重新执行。
- 浏览器完整验收、阶段完整回归：NOT_RUN，本轮没有界面修改，也不是阶段收尾，不扩大执行范围。
