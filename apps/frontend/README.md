# Frontend - Vue3

> 版本 v0.2_20260826 | 视图14 (`apps/frontend/src/views`) | 路由16组 | 完成度92% | 构建 `vite v6.4.3 2987 modules in 7.21s`

## 启动

```bash
pnpm install --ignore-scripts
pnpm --filter frontend dev        # http://localhost:5173 代理 /api→8000 ws:true
pnpm --filter frontend build      # vue-tsc --noEmit && vite build
pnpm --filter frontend check      # vue-tsc --noEmit && vite build (turbo check)
```

## 路由与视图（14, 2026-08-26 修正 12→14）

`apps/frontend/src/router/index.ts:3` 懒加载 14视图：

| # | 路径 | 视图 | 说明 |
|---|------|------|------|
| 1 | `/` | `HomeView.vue` | 首页 32px 标题 + 3白卡 |
| 2 | `/health` | `HealthCheck.vue` | 双探针 `/health` + `/api/v1/health` |
| 3 | `/goals` | `GoalsView.vue` | 目标CRUD |
| 4 | `/calendar` | `CalendarView.vue` | FullCalendar 日历 |
| 5 | `/week` | `WeekView.vue` | 周视图 |
| 6 | `/gantt` | `GanttView.vue` | 甘特图 |
| 7 | `/tasks/batch` | `TaskBatchView.vue` | 批量改期 |
| 8 | `/graph` | `KnowledgeGraphView.vue` | ECharts Graph force |
| 9 | `/dashboard` | `DashboardView.vue` | 3图 288k |
| 10 | `/mcp` | `MCPView.vue` | servers/tools 调用 |
| 11 | `/experiments` | `ExperimentsView.vue` | 对比实验柱状+折线 (新增 2026-08-26) |
| 12 | `/large-screen` | `LargeScreenView.vue` | 大屏驾驶舱 4卡片+趋势 (新增 2026-08-26) |
| 13 | `/rag` | `RAGView.vue` | 知识入库检索 |
| 14 | `/reflection` | `ReflectionView.vue` | 周反思报告 |

> 旧文档 12视图未含 `ExperimentsView`/`LargeScreenView`, 现14已验 `vite build 2987 modules` 必过。

## 代理与构建

`apps/frontend/vite.config.ts:16`：

```ts
proxy: {
  '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true, configure: (proxy)=>proxy.on('proxyReq',(r)=>r.setHeader('Connection','keep-alive')) },
  '/health': { target: 'http://localhost:8000', changeOrigin: true }
}
build: { chunkSizeWarningLimit: 1500, manualChunks: { 'vendor-vue': ['vue','vue-router','pinia'], 'vendor-naive': ['naive-ui'], 'vendor-echarts': ['echarts','vue-echarts'], 'vendor-calendar': ['@fullcalendar/...'], 'vendor-axios': ['axios'] } }
scripts: { dev: "vite --port 5173", build: "vue-tsc --noEmit && vite build", check: "vue-tsc --noEmit && vite build" }
```

## 验证（2026-08-26 实测）

```bash
$env:PYTHONPATH="E:/paper project/apps/server"; py -m pytest tests/ -q  # 35 passed in 26.26s
npm run build --prefix apps/frontend  # vite v6.4.3 2987 modules in 7.21s (vue-tsc OK)
# 产物：dist/assets/vendor-naive 855k, vendor-echarts 284k, vendor-calendar 259k, vendor-vue 104k
```

## 样式

Apple 克制 `#1d1d1f` / `#86868b` / `#f5f5f7` + `-apple-system` 字体栈 + `n-card` 无边框+16圆角+留白 `max-w 1280 px-10 py-12`，详见 `02-需求与设计/06-UI设计规范.md`。

## 2026-08-26 增补

- 修正 `apps/web`→`apps/frontend`, 视图 12→14, 路由 13→16组(66端点), 完成度62%→92%
- 新增 sidecar/WAL/HNSW/asearch 说明同步 `README.md` 与 `00-管理` 核验报告

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-23 | v0.1 | 初始化 |
| 2026-08-26 | v0.2 | 增补14视图/16组路由/完成度92%/sidecar/WAL/HNSW/asearch/验证 7.21s |
