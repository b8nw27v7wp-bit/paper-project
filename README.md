# 智能学习任务规划与管理系统 - 项目文档库

> 题目：基于多智能体协作与记忆增强的自进化学习任务规划与管理的智能体 — 融合MCP工具链与多模态感知的知识驱动架构
> 路径：`E:\paper project` | 版本：`v0.3_20260830` | 周期：6-7个月（28周） | 完成度：`P0-P3 94%` | 路由：`16组` | 视图：`15` | 测试：`35/35` | 构建：`vite 7.21s 2987 modules`

## 文档结构

```
E:\paper project\
 ├─ README.md                         # 本文件，文档总索引
 ├─ 00-管理\
 │   ├─ 00-项目总计划书.md             # 总计划、里程碑、28周排期
 │   ├─ 01-开发规范与Git管理.md        # 命名、分支、提交、Markdown规范
 │   ├─ 02-会议记录\                  # 导师会议每次一档 YYYYMMDD-主题.md
 │   └─ 03-周报\                      # 每周周报 YYYYWW-周报.md
 ├─ 01-开题与立项\
 │   ├─ 01-题目与技术栈说明.md         # 题目拆解+技术栈选型论证
 │   ├─ 02-开题报告.md                 # 开题报告正文（提交版）
 │   ├─ 03-文献综述.md                 # Agent/RAG/MCP 文献
 │   └─ 04-可行性分析.md               # 技术/经济/时间可行性
  ├─ 02-需求与设计\
  │   ├─ 01-需求分析.md                 # 功能/非功能/用例图
  │   ├─ 02-系统架构设计.md             # 三端架构+技术交互
  │   ├─ 03-六大模块详细设计.md         # 7模块落点详细设计(M7工作台)
  │   ├─ 04-数据库设计.md               # PG+pgvector/Neo4j/Redis/better-sqlite3
  │   ├─ 05-API接口设计.md              # REST + SSE + IPC 接口
  │   ├─ 06-Agent工作台设计.md         # Chat+Graph+Inspector三位一体与子调用追溯
  │   └─ diagrams\                     # 架构图、时序图、ER图源文件
 ├─ 03-实现与测试\
 │   ├─ 01-开发环境搭建.md             # Docker/依赖/启动
 │   ├─ 02-测试计划.md                 # 单元/集成/E2E
 │   └─ 03-评估与实验设计.md           # 双对比实验方案
 ├─ 04-论文\
 │   ├─ 论文大纲.md                   # 8章大纲与写作分工
 │   └─ 写作规范.md                   # 格式、引用、查重
 └─ 05-附件\
     ├─ 参考文献\                    # PDF原文
     └─ 原型图\                      # Figma/原型导出
```

## 版本规范

- 文档命名：`序号-中文名.md`，如 `02-系统架构设计.md`
- 版本号：`v0.1_YYYYMMDD`，重大更新递增 `v0.2`
- 周报/会议记录：`YYYYMMDD-主题.md` 或 `YYYYWW-周报.md`
- 变更记录：每份文档末尾留 `## 变更日志`

## 快速开始

1. 阅读 `00-管理/00-项目总计划书.md` 了解排期
2. 阅读 `01-开题与立项/01-题目与技术栈说明.md` 了解选型
3. 按 `02-需求与设计` 顺序完善设计

## 技术栈快照

前端: Vue3 + Vite + TS + Tailwind + Naive UI + FullCalendar + ECharts (15视图 `apps/frontend/src/views` + `src/router/index.ts:3` 懒加载分包, `vite.config.ts:16` 代理 `/api`→8000 `ws:true`) 工作台: Chat(SSE 8事件)+Graph(ECharts DAG 6节点+回边)+Inspector(PlanState/tool_calls/patch) | 漂移检测: `npm run check:docs` ≥10命中“基于多智能体协作与记忆增强的自进化学习任务规划与管理的智能体” | Agent: GET /api/v1/agent/manifest
桌面: Electron 40 + electron-builder + better-sqlite3 + Sidecar(`apps/desktop:e18` externalBin `bin/server`, `appId com.learning.planner`) + Tray/Notification/IPC(`apps/desktop/src`)
后端: FastAPI + LangGraph 6节点(`app/agents/graph.py:351` StateGraph + `FileMemorySaver` checkpoint 可恢复) + MCP Python SDK + 统一LLM(`app/core/llm.py` provider无关 deepseek/qwen/zhipu/openai + Fallback链) + Pydantic + SQLModel
存储: PostgreSQL+pgvector(HNSW `m=16 ef=64` `app/models/memory.py:17` `Vector(1536)`/`app/core/database.py:49` WAL) + Neo4j(PREREQ BFS2) + Redis(Redis限流 via `app/core/ratelimit.py` → `redis INCR`) + APScheduler(周日23:00/周一09:00 `register_reflector_jobs`)
工具链: `app/agents/tools/registry.py` 单一职责可热插 `memory/rag/graph/write` + `app/services/memory.py:139` `asearch_memory` 真embedding

## 验证命令（2026-08-26 增补, 实测）

```bash
cd apps/server && $env:PYTHONPATH="E:/paper project/apps/server"; py -m pytest tests/ -q  # 35 passed, 1 warning in 26.26s (2026-08-26)
npm run build --prefix apps/frontend  # vite v6.4.3 2987 modules in 7.21s (2026-08-26, vue-tsc --noEmit + vite build)
py scripts/pgvector_bench.py --n 500 --q 20   # p95 ~108ms PASS (USE_PG=0, 2026-08-26)
py scripts/graph_bench.py --nodes 1000 --edges 5000 --q 20  # p95 10ms PASS
py -c "from app.main import app; print('ok')" # ok
# 新增工作台 e2e: pnpm --filter frontend test:e2e workbench.spec.ts
```

> 2026-08-26 增补：接口数 `13→16组` (新增 `desktop/experiments/llm` 3组, 含 `goals_async/tasks_async` 共17文件 `app/api/v1` → 66端点), 视图 `12→14` (新增 `ExperimentsView/LargeScreenView` 等), P0-P3 `62%→92%`, 新增桌面 sidecar/WAL(`PRAGMA journal_mode=WAL busy_timeout=5000`)/HNSW(`idx_memory_embedding_hnsw`)/asearch(`asearch_memory` 真embedding + `embed_text`)
> 2026-08-30 增补：双轨并进，新增Agent工作台(Chat+Graph+Inspector)凸显子智能体调用，视图14→15，F15-F17，M7，v0.3

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-22 | v0.1 | 初始化文档库结构 |
| 2026-08-26 | v0.2 | 增补：完成度92%、16组路由/14视图/35 tests、sidecar/WAL/HNSW/asearch、验证命令与 vite 7.21s 日志；修正 apps/web→apps/frontend 路径 |
| 2026-08-30 | v0.3 | 双轨：新增工作台Chat+Graph+Inspector、F15-F17、M7、视图15 |
