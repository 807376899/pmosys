# PMO Frontend

## Stack

- React
- Vite
- TypeScript
- Custom editorial dashboard styling prepared for later Shadcn/ui migration

## Run

```powershell
cd frontend
npm install
npm run dev
```

Vite dev server defaults to `http://localhost:5173` and proxies `/api` to `http://127.0.0.1:8000`.

## Current screens

- PMO 工作台首页
- 五大统筹视角卡片
- 项目列表与批量勾选
- 批量流转预检与执行侧栏
- 导入预览与确认区域

## Next recommended additions

- 项目详情页与单项目状态流转
- React Router 页面拆分
- Shadcn/ui 组件替换当前基础表单控件
- TanStack Table 升级表格交互
