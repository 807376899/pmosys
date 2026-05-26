# PMO 项目管理系统

面向 PMO 治理视角的项目全生命周期管理系统，覆盖项目申报、评审、立项、送审、采购、实施、试用、验收、关闭，以及暂停和终止等分支流程。当前主线正在从 Streamlit 单体应用迁移到 FastAPI + React 的前后端分离架构。

## 当前架构

- 后端：FastAPI + SQLite，数据库默认使用项目根目录下的 `pmo.db`，支持 WAL、连接上下文管理、项目 CRUD、状态流转、批量流转、导入导出、工作流只读接口和 dashboard 聚合接口。
- 前端：React + Vite + TypeScript，当前提供 PMO 工作台、统筹视角卡片、项目列表、批量流转预检/执行、导入预览等基础界面。
- Legacy 入口：`app.py`、`components/`、`lib/`、`utils/` 保留为 Streamlit 兼容入口，后续 React 功能补齐后再决定归档或删除。

## 环境要求

- Python 3.11+
- Node.js LTS 或更高版本
- Windows PowerShell 或等价终端

## 后端运行

```powershell
# 安装 Python 依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 启动 FastAPI，端口 8000
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- API 文档：`http://localhost:8000/docs`
- OpenAPI：`http://localhost:8000/openapi.json`
- 健康检查：`http://localhost:8000/api/v1/health`

如需指定数据库路径：

```powershell
$env:PMO_DB_PATH="E:\codex\pmosys\pmo.db"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 前端运行

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Vite 默认运行在 `http://localhost:5173`，并把 `/api` 代理到 `http://127.0.0.1:8000`。本地联调时请先启动后端，再启动前端。

## Legacy Streamlit 运行

旧入口仍可用于对照和兜底：

```powershell
.\run.ps1 -Port 5000
```

或直接运行：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 5000 --server.address 0.0.0.0 --server.headless true
```

访问地址：`http://127.0.0.1:5000`。

## 测试与构建

```powershell
# 后端测试
.\.venv\Scripts\python.exe -m pytest backend\tests

# 前端生产构建
cd frontend
npm.cmd run build
```

当前已验证：

- 后端测试：12 passed
- 前端构建：TypeScript + Vite build 通过

## 关键 API 能力

- `GET /api/v1/projects`：项目列表，支持状态、统筹分组、关键词、部门、负责人、项目类型、预算、年份等筛选。
- `POST /api/v1/projects`：创建项目，自动生成项目编号。
- `PATCH /api/v1/projects/{id}`：白名单字段更新。
- `POST /api/v1/projects/{id}/transitions`：单项目状态流转。
- `POST /api/v1/projects/batch-transition/preview`：批量流转预检。
- `POST /api/v1/projects/batch-transition`：批量流转执行。
- `GET /api/v1/dashboard/summary`：项目总览和状态统计。
- `GET /api/v1/dashboard/groups`：五个 PMO 统筹视角及预算聚合。
- `POST /api/v1/imports/projects/preview`：导入预览。
- `POST /api/v1/imports/projects/commit`：确认导入。
- `GET /api/v1/exports/projects`：导出当前筛选项目。

## 后续更新规划

优先补齐 React 前端，让它逐步替代 Streamlit：

1. 加入 React Router，拆分工作台、项目详情、新建/编辑、导入、工作流页面。
2. 补齐项目详情页、状态历史、单项目流转、创建项目、项目编辑。
3. 表格升级分页、排序、部门/负责人/项目类型/预算/年份筛选。
4. 在统筹视角卡片展示后端已返回的预算聚合字段。
5. 后端继续硬化：迁移 FastAPI lifespan、完善环境变量说明、扩展接口测试覆盖。

## 注意事项

- `pmo.db` 是本地运行时数据库，已加入忽略列表。
- `frontend/package-lock.json` 应随前端依赖一起提交，确保团队安装结果一致。
- PowerShell 可能因执行策略阻止 `npm` 脚本，推荐使用 `npm.cmd`。
- `lib/workflow.py` 仍被新后端种子数据复用，不属于无用代码。
