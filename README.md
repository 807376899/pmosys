# PMO 项目管理系统

面向 PMO 的项目治理工作台。系统以 **Stage + ProjectWorkItem** 为核心：固定 Stage 用于项目库统计与治理决策，Work Item 用于记录评审、预算、采购准备等可并行推进的具体工作，避免把日常事项重新塞回一棵“状态树”。

当前产品主入口是 React 工作台；FastAPI 提供本地 API 和 SQLite 数据持久化。根目录的 Streamlit 文件仅作为旧版本保留，不是当前推荐运行方式。

## 需求与能力入口

当前业务与交互只由[需求基线](docs/requirements/pmo-lifecycle-requirements.md)定义。Stage与推进见REQ-GOV-001/002/003，事项见REQ-WI-001至004，外部条件见REQ-EC-001至003，工作台见REQ-UI-001至008。需求已确认不表示实现或验收通过；实际证据见[验收记录](docs/acceptance/README.md)。

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

验证范围、结果状态与证据要求只在[AGENTS.md](AGENTS.md)定义。文档检查：` .\.venv\Scripts\python.exe scripts\check_docs_governance.py`；隔离测试：` .\.venv\Scripts\python.exe -m pytest tests\test_docs_governance.py -q`。

## 常用 API 入口

完整接口以 FastAPI 的 `/docs` 为准。常用资源包括：

- `GET /api/v1/projects`：工作台项目列表投影（Stage、事项摘要、下一关键节点、推进信息、外部条件投影与当前有效预算）。
- `POST /api/v1/projects/batch-work-items`：向多个项目下发事项。
- `POST /api/v1/projects/batch-include-in-advancement`：批量纳入推进。
- `POST /api/v1/projects/batch-defer-advancement`：批量暂缓推进并回到未实施。
- `POST /api/v1/projects/{id}/early-preparation`：未立项项目登记提前推进准备。
- `GET /api/v1/work-item-templates` 与 `GET /api/v1/work-packages`：常用事项和工作包。
- `POST /api/v1/projects/{id}/work-items/{itemId}/progress-logs`：追加事项过程记录。
- `GET/POST /api/v1/external-constraint-templates`：管理可复用的外部约束模板。
- `POST /api/v1/projects/{id}/external-constraints`：为项目建立外部约束；办理规则按REQ-EC-001@v1，运行接口以OpenAPI为准。

## 需求与治理文档

以下文档用于长期保留需求和决策，避免更换对话后丢失约束：

- [需求基线](docs/requirements/pmo-lifecycle-requirements.md)
- [决策日志](docs/requirements/decision-log.md)
- [验收清单](docs/requirements/acceptance-checklist.md)
- [API 文档说明](docs/api/README.md)
- [协作约束](AGENTS.md)

变更协议与按影响更新文档的要求见[AGENTS.md](AGENTS.md)。

## 数据与迁移说明

- 项目纠错与软删除规则见REQ-PRJ-001@v1。
- 当前领域边界与后置模块见REQ-GOV-001@v1。
- 根目录 `app.py`、`components/`、`lib/` 属于旧版 Streamlit 兼容实现；`run.ps1` 是当前 FastAPI 的本地启动脚本。
