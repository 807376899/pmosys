# 无损金额精度定向验证记录（2026-09-23）

关联：REQ-PRJ-001@v5、REQ-PRJ-003@v8、REQ-EC-003@v4、REQ-UI-003@v13、REQ-UI-006@v11、REQ-UI-007@v5、REG-MONEY-001。

## 已执行

| 层级 | 状态 | 证据 |
| --- | --- | --- |
| API | PASS | `backend/tests/test_external_constraints.py backend/tests/test_money_precision.py -q` 共 27 项通过。覆盖 `12.5896` 项目金额与影响有效预算约束解除、`12.5000` 规范化、非法值拒绝及项目/约束/资金/合同投影。 |
| Build | PASS | `npm.cmd --prefix frontend run build` 通过（TypeScript 与 Vite 生产构建）。 |
| Browser | NOT_RUN | 尚未以真实浏览器逐项验证金额文本输入、保存、刷新、sticky 表头/详情页头、Stage 列偏好与角色字段隐藏。 |

## 说明

本记录只证明定向后端自动化结果，不将 API 结果替代浏览器验收。现有数据库 REAL 测试值未迁移或改写；读取以新精度文本列优先、旧 REAL 回退。
