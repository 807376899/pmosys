# 部门排序持久化定向验证（2026-10-15）

## 范围

- 需求/验收：`REQ-PRJ-002@v2`、`AC-005`
- 代码状态：`dd3777c` 基础上的 dirty 工作树；本次仅涉及部门排序读取、列表/导出排序、基础配置文案、定向测试与验收清单。
- 环境：本机 Python 虚拟环境、FastAPI TestClient、Vite 生产构建；浏览器为本机 `127.0.0.1:5173`。

## 实际证据

| 层级 | 结果 | 步骤与观察 | 证据 |
| --- | --- | --- | --- |
| API | PASS | 新建 `Z/A/M` 三个部门项目，环境默认顺序设为 `Z→A→M`，仅保存 `M` 为第一。重新读取部门、默认项目列表及导出均为 `M→A→Z`；证明持久化排序优先，未配置部门按名称排后。 | `backend/tests/test_projects_crud.py::test_persisted_department_order_controls_metadata_list_and_export_after_reload`；受影响测试共 `35 passed` |
| Build | PASS | 前端生产构建完成。 | `npm.cmd --prefix frontend run build` |
| Document | PASS | 文档结构检查及其测试通过；`AC-005` 增加重载与导出排序预期。 | `scripts/check_docs_governance.py`；`tests/test_docs_governance.py`：`26 passed` |
| Browser | NOT_RUN | 已通过正常入口打开基础配置并观察到新文案“项目分类保存以后无法修改。”；为避免改变当前运行库中的既有部门顺序，未执行浏览器拖拽保存、刷新后的写入链路。 | 本机浏览器静态文案观察；待补做拖拽→刷新→列表/导出验证 |

## 汇总

总体为 `NOT_RUN`：所需浏览器拖拽写入/刷新路径尚未执行；API、构建和文档证据不能替代该层验证。
