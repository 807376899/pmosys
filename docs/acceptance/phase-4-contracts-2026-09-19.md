# 2026-09-19 合同与验收定向验证记录

| 字段 | 内容 |
| --- | --- |
| 日期/运行标识 | 2026-09-19 / CONTRACT-20260919-01 |
| 需求/验收版本 | REQ-GOV-001@v4、REQ-CONTRACT-001@v1、REQ-CONTRACT-002@v1、REQ-UI-003@v8、REQ-UI-005@v6、REQ-UI-006@v7；AC-001、AC-019、AC-021、AC-022、AC-030、AC-031 |
| 代码版本 | 当前工作树，包含未提交 Phase 3 与合同实现改动；未将该记录视为提交版本 |
| 环境 | FastAPI TestClient 临时 SQLite；前端 Vite 生产构建 |

## 2026-09-21 规则更新与定向验证

| 字段 | 内容 |
| --- | --- |
| 需求/验收版本 | REQ-GOV-004@v6、REQ-CONTRACT-001@v2、REQ-CONTRACT-002@v2、REQ-UI-003@v9、REQ-UI-005@v7、REQ-UI-006@v8；AC-003、AC-019、AC-021、AC-022、AC-030、AC-031 |
| API | `./.venv/Scripts/python.exe -m pytest backend/tests/test_advancement_drafts.py backend/tests/test_contracts.py -q`：PASS（10 passed）。覆盖正常年度确认无理由、可空项目分摊及差额、履约中验收、验收通过后手动完成、历史合同补录。 |
| Build | `npm.cmd --prefix frontend run build`：PASS。 |
| Browser | NOT_RUN（部分只读观察）。已在项目详情打开已完成项目的“补录历史合同”表单，确认可见补录原因和当前项目可选分摊金额；为保护现有导入数据，未提交年度确认、合同分摊、验收、完成或历史补录，不将 API/Build 结果替代浏览器写入证据。 |

## 2026-09-22 列表优先与历史补录收敛

| 字段 | 内容 |
| --- | --- |
| 需求/验收版本 | REQ-CONTRACT-001@v3、REQ-UI-003@v10、REQ-UI-005@v8、REQ-UI-006@v9；AC-019、AC-021、AC-022、AC-030、AC-031 |
| API | `./.venv/Scripts/python.exe -m pytest backend/tests/test_contracts.py -q`：PASS（7 passed）。覆盖草稿合同编号必填、紧凑合同条目投影、分摊、验收、完成门槛及多个已完成项目历史补录关联。 |
| Build | `npm.cmd --prefix frontend run build`：PASS。 |
| Browser | NOT_RUN（只读观察）。工作台已完成项目“暂无合同”点击后进入右侧合同列表；详情补录表单可见必填合同编号、补录原因及两个已完成项目的可选关联。为保护当前数据未提交表单，保存后返回列表与刷新持久化仍待隔离数据写入验证。 |

## 已执行证据

| 验证层 | 命令/步骤 | 结果 | 证据 |
| --- | --- | --- | --- |
| API | `./.venv/Scripts/python.exe -m pytest backend/tests/test_contracts.py -q` | PASS | 2 passed：草稿创建、履约升级必填、编号唯一、多项目摘要同步、已完成项目纠错关联、进展软删除、验收历史、最后关联保护 |
| Build | `npm.cmd --prefix frontend run build` | PASS | TypeScript 构建与 Vite production build 成功 |
| Browser | 工作台推进中项目合同列→“+ 添加合同”；项目详情视觉顺序 | NOT_RUN | 已观察到合同列、直接进入填写表单，以及概况→外部约束→合同→进度跟踪顺序；未提交真实合同，也未完成多项目、状态、验收、已完成项目只读及刷新写链路，故 Browser 层仍为 NOT_RUN |

## 汇总

AC-030、AC-031 及受影响 UI 验收项的 Browser 层均为 `NOT_RUN`，因此本记录不宣称合同交互验收通过。后续浏览器验证须覆盖工作台单项目/多选创建、关联项目同步、合同进展与验收、已完成项目明确编辑纠错、各目标视口操作台布局和刷新持久化。
