# PMO 项目管理系统

面向 PMO 的项目治理工作台。系统以 **Stage + ProjectWorkItem** 为核心：固定 Stage 用于项目库统计与治理决策，Work Item 用于记录评审、预算、采购准备等可并行推进的具体工作，避免把日常事项重新塞回一棵“状态树”。

当前产品主入口是 React 工作台；FastAPI 提供本地 API 和 SQLite 数据持久化。根目录的 Streamlit 文件仅作为旧版本保留，不是当前推荐运行方式。

## 当前可用能力

- 五个固定 Stage：未立项、项目库—未实施、项目库—推进中、已完成、已废弃。
- 高密度 PMO 工作台：Stage 卡片、项目筛选、总览/阶段跟踪视图、当前进展摘要与下一关键节点。
- 工作项（Work Item）：批量下发、单项目例外新增、常用事项、工作包、状态/计划日期/重点关注维护，以及连续进展记录。
- 外部约束（External Constraint）：以轻量治理对象记录预算核定、备案、准入等外部阻断条件；办理过程仍由 Work Item 管理。
- 主流程排序：主流程事项按 `flow_group + sequence_rank` 排列；独立事项不抢占下一关键节点。
- 推进治理：纳入推进、暂缓推进、结束推进周期、未立项项目的提前推进准备，以及已废弃项目的特批恢复。
- PMO 批量操作：纳入推进、调整 Stage、添加事项、应用工作包；批次入口明确留待后续实现。
- 项目导入、导出、类型目录、项目编号生成和统一审计事件。

## 领域口径

| 对象 | 回答的问题 |
| --- | --- |
| Stage | 项目整体处于哪个 PMO 治理口径？ |
| ProjectWorkItem | 项目现在具体在推进什么？ |
| WorkItemProgressLog | 事项尚未完成时，中间发生了什么？ |
| Milestone | 已发生了哪些关键事实？ |
| ProjectAdvancementRecord | 某年度推进计划是否纳入、暂缓或结束？ |
| ExternalConstraint | 是否存在仍阻断项目推进的外部治理条件？ |
| AuditEvent | 谁在何时做了什么操作？ |

### 关键规则

- Stage 只有五个固定值，不能用“送审中”“采购中”等旧小状态作为 Stage 附属显示。
- “项目库—未实施”进入“项目库—推进中”只能通过 PMO 的**纳入推进**动作；预算审核等事项不会自动改变这一管理口径。
- 已完成、不适用、已取消或已跳过的主流程事项不参与下一关键节点；暂停事项默认仍是阻塞节点。
- 事项取消是独立留痕动作，不增加新的事项状态；已完成事项应通过重开处理，不能覆盖历史完成记录。
- 未立项项目不能直接纳入推进，只能登记“提前推进准备”，Stage 保持未立项。
- 常用事项是单项复用，工作包是一组事项复用；二者均须由 PMO 显式保存。
- 外部约束三态为 `true / false / unknown`：只有已确认适用范围且所有**阻断性**约束均已解除或不适用时为 `true`；没有约束但未确认范围仍为 `unknown`。非阻断约束不影响该判断。
- 当前有效预算由统一投影计算，并同时返回来源：外部预算核定、历史审核预算或初始预算。

## 技术结构

```text
pmosys/
├── backend/                 # FastAPI、SQLite 迁移、领域服务与 API 测试
│   └── app/
├── frontend/                # React + TypeScript + Vite 工作台
├── docs/
│   ├── requirements/        # 需求基线、决策日志、验收清单
│   └── api/                 # API 使用说明与集合
├── app.py、components/、lib/ # 旧版 Streamlit 代码，仅保留迁移参考
└── pmo.db                   # 本地运行时数据库（自动创建，不提交）
```

## 环境要求

- Python 3.11 或更高版本
- Node.js 18 或更高版本
- Windows PowerShell（其他终端亦可）

## 本地启动

先启动后端，再启动前端。首次运行时，后端会自动初始化 SQLite 数据库与迁移。

### 1. 后端（FastAPI）

```powershell
# 首次运行会创建 .venv、安装依赖并启动 API
.\run.ps1
```

`run.ps1` 仅使用本机安装的 Python 3.11+。若提示未找到 Python，请先安装 Python 并重新打开 PowerShell：

```powershell
winget install --id Python.Python.3.11 --exact
```

如需手动创建环境，可在新的 PowerShell 窗口中执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

后端地址：

- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 健康检查：[http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

默认数据库为项目根目录的 `pmo.db`。如需指定路径：

```powershell
# 在仓库根目录执行；数据库跟随当前项目目录迁移
$env:PMO_DB_PATH = Join-Path $PWD "data\pmo.db"
.\run.ps1
```

不要在项目配置、文档或脚本中写入个人电脑的盘符路径。迁移项目时，复制仓库目录即可；如需保留既有数据，再将原 `pmo.db` 一并复制到新项目根目录或通过 `PMO_DB_PATH` 指向迁移后的相对位置。

### 2. 前端（React）

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

工作台地址：[http://127.0.0.1:5173](http://127.0.0.1:5173)。开发服务器会将 `/api` 代理到 `http://127.0.0.1:8000`。

> PowerShell 因执行策略无法直接调用 `npm` 时，请使用 `npm.cmd`。

## 测试与构建

```powershell
# 后端测试（先运行 .\run.ps1 创建本地虚拟环境）
.\.venv\Scripts\python.exe -m pytest backend\tests -q

# 前端类型检查与生产构建
cd frontend
npm.cmd run build
```

涉及工作台或项目详情的改动，除测试与构建外，还必须在浏览器中核对实际交互和布局；构建通过不能替代浏览器验收。

## 常用 API 入口

完整接口以 FastAPI 的 `/docs` 为准。常用资源包括：

- `GET /api/v1/projects`：工作台项目列表投影（Stage、事项摘要、下一关键节点、推进信息、外部约束三态与当前有效预算）。
- `POST /api/v1/projects/batch-work-items`：向多个项目下发事项。
- `POST /api/v1/projects/batch-include-in-advancement`：批量纳入推进。
- `POST /api/v1/projects/batch-defer-advancement`：批量暂缓推进并回到未实施。
- `POST /api/v1/projects/{id}/early-preparation`：未立项项目登记提前推进准备。
- `GET /api/v1/work-item-templates` 与 `GET /api/v1/work-packages`：常用事项和工作包。
- `POST /api/v1/projects/{id}/work-items/{itemId}/progress-logs`：追加事项过程记录。
- `GET/POST /api/v1/external-constraint-templates`：管理可复用的外部约束模板。
- `POST /api/v1/projects/{id}/external-constraints`：为项目建立外部约束；`.../actions` 以开始办理、补充、登记结论、不再适用或结论失效等动作更新。

## 需求与治理文档

以下文档用于长期保留需求和决策，避免更换对话后丢失约束：

- [需求基线](docs/requirements/pmo-lifecycle-requirements.md)
- [决策日志](docs/requirements/decision-log.md)
- [验收清单](docs/requirements/acceptance-checklist.md)
- [API 文档说明](docs/api/README.md)
- [协作约束](AGENTS.md)

业务或实现改动前，先判断它属于 Stage、ProjectWorkItem、Milestone、Batch、BusinessRecord、AuditEvent 或未来采购实体；并同步更新上述治理文档。

## 数据与迁移说明

- 旧数据中显示为 `???` 的项目名称无法从数据库自动还原，须由 PMO 人工补正并保留审计记录。
- Batch、供应商、合同、采购包、BusinessRecord 关联与共享附件是后续领域模块；当前 UI 不将其伪装为已可用功能。
- 根目录 `app.py`、`components/`、`lib/` 属于旧版 Streamlit 兼容实现；`run.ps1` 是当前 FastAPI 的本地启动脚本。
