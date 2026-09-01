# 答辩PPT大纲（15页）

> 版本 v0.4_20260830 | 对应论文8章 + 演示 | 每页要点≤5条 + 演讲备注 | 时长15分钟（每页约1分钟，演示2分钟）

## 第1页 题目页

- 题目：基于多智能体协作与记忆增强的自进化学习任务规划与管理的智能体——融合MCP工具链与多模态感知的知识驱动架构
- 作者/导师/学院/日期（2026-08-30），关键词：LangGraph / pgvector / GraphRAG / MCP / 双轨工作台
- 完成度94%（P0-P3），16组路由 15视图 M7 35/35 vite 6.3s/7.21s
- 二维码：`http://localhost:5173` 演示 + `GET /health` + GitHub

> 备注（30s）：问候与题目解读，强调“可感知-可规划-可执行-可反思”闭环与三端单后端，预告双轨工作台演示。

## 第2页 背景与痛点

- 传统计划静态通用：一次生成、无个性化、无反馈
- 学习场景复杂：考研/六级/考证多DDL、多依赖、易拖延
- 现有工具割裂：日历/待办/笔记/图谱不互通
- 研究问题：如何让计划“自进化”且可观测可调试

> 备注（45s）：用1个考研6周案例说明冲突与依赖缺失，引出动机，不展开技术。

## 第3页 相关技术

- LangGraph StateGraph 6节点协作 + checkpoint可恢复
- RAG/GraphRAG + pgvector HNSW (m16 ef64) + Neo4j PREREQ
- MCP协议工具链（calendar/todo/search 热插）
- Electron + Vue3 + FastAPI + SSE 8事件

> 备注（45s）：一句话一技术，只讲选型理由（LangGraph可回溯、pgvector单库向量、MCP热插），不念参数。

## 第4页 需求分析

- 用户与用例图：学习者/导师，F01-F14（目标/任务/规划/记忆/图谱/MCP/反思/工作台/大屏）
- 非功能：规划<15s、检索<1s、图<3s、SSE首字节<2s、查重<15%
- 约束：单人全栈、模型费用用DeepSeek-V3、Neo4j限2G
- 引用：01-需求分析

> 备注（30s）：F01-F14只列核心4类，用用例图占位，强调可测非功能阈值。

## 第5页 总体架构（C4）

- C4图：Context→Container（Web/Electron/Server/pg/neo4j/redis）→Component（6子系统）
- 三端单后端：`apps/frontend` 同构 + `apps/desktop/electron` sidecar `externalBin/bin`
- 数据双模：`USE_PG` 切 SQLite TEXT(JSON) vs pgvector Vector(1536)
- 部署：Docker Compose一键起 + `better-sqlite3` WAL

> 备注（60s）：指图讲数据流“Goal→multi_graph→SSE→Workbench→Task→Reflection”，点出双轨与双写。

## 第6页 详细设计（上）M1-M3

- M1 协作：`app/agents/graph.py:351` 6节点线性+replan回边，`Thread_id` + `plan_store` 内存+DB
- M2 记忆：`app/models/memory.py:17` Vector(1536) + `app/services/memory.py:139` asearch + 30天衰减
- M3 图谱：`neo.py:113` UNWIND 1k批 + `sqlite_graph.py` 三索引，三级回退

> 备注（60s）：画6节点DAG，强调Critic驳回是合理性+1分的关键，记忆与图谱互补。

## 第7页 详细设计（下）M4-M7

- M4 MCP：`app/mcp/client.py:335` 3次退避，`mcp.json` mock可切npx
- M5 多模态：Qwen-VL 拍照→OCR→任务
- M6 反思：`register_reflector_jobs` 双Job + `_notify_log` 拉取
- M7 双轨工作台：`WorkbenchView.vue` 三栏 + `GET /graph + /inspector` + 5m缓存 + 联合索引

> 备注（60s）：M7是创新增量，点出Chat+Graph+Inspector与8事件 `id/retry`，为演示铺垫。

## 第8页 实现亮点

- 统一LLM `app/core/llm.py` UnifiedClient 4链fallback
- 数据库 `app/core/database.py:26` WAL + `async_engine` + `idx_agent_trace_agent_created`
- 工具注册表 `app/agents/tools/registry.py` 单一职责热插
- 前端 `vite.config.ts:16` 代理 `/api→8000 ws:true` + ECharts DAG

> 备注（45s）：每亮点配代码行号，强调“可热插、provider无关、plan_store不丢”。

## 第9页 演示（工作台三栏动图占位）

- 动图占位：`WorkbenchView.vue` Chat气泡 + ECharts 6节点DAG + Inspector JsonView穿透，`trace_id` 贯穿
- 操作：新建Goal“30天过六级”→一键规划→Graph高亮 `replan`→点击节点看 `state/logs/patch`
- 指标：Graph渲染 187ms <500ms，Inspector 94ms <300ms，SSE TTFB 890ms <2s（前端埋点）
- 二维码：现场扫码进 `/workbench`

> 备注（90s）：现场或录屏演示，不念字；若离线则播“三栏动图.mp4”，数据来源 `performance.now()` + `cache:graph`。

**图占位说明**：图D-1 工作台三栏动图（数据来源：`apps/frontend/src/views/WorkbenchView.vue` 实录，`trace_id` 复现）。

## 第10页 测试

- 单元 35/35：`pytest tests/ -q 35 passed 26.26s`（边界8+安全8+图6+记忆5+调度4）
- 集成：SSE/ pgvector/ Neo4j+MCP/Electron IPC 全链路通过
- E2E：`workbench.spec.ts` 5例（Goal→规划→Graph→Inspector→大屏）Playwright通过
- 构建：`vue-tsc` 0 error，`vite build` 2987 modules 7.21s→6.3s，`ruff` 0 E

> 备注（45s）：一表带过，强调“全量读后改、check全过再提交”，可放 `playwright-report` 截图。

## 第11页 实验A 多Agent vs 单Agent

- 设计：20 Goal分层，单Agent直出 vs 6节点协作，盲评1-5分（3人）+ 冲突率 + 依赖缺失率
- 结果：合理性 3.21→4.18 (p<0.001,d1.7)，冲突 34.6%→8.3% (p<0.001)，缺失 36.8%→13.5%
- 图占位：图7-1 箱线图 + 图7-2 柱状图（数据来源：`data/experiments/expA_20goals.csv` + Langfuse）
- 结论：H1成立，Critic回边是关键

> 备注（60s）：只读加粗行，点出t/p/d与大效应，不展开每Goal。

## 第12页 实验B 有记忆 vs 无记忆

- 设计：1用户7日log，无记忆Top0 vs 有记忆Top5+图谱PREREQ，完成率主指标
- 结果：7日完成率 60.4%→73.1% (+12.7%, p0.003,d1.84)，拖延 28.3%→16.5%，调整 5.2→4.1次
- 图占位：图7-3 7日折线图（数据来源：`stats/trend` + `task_execution_log`）
- 结论：H2成立，记忆减少重复试错

> 备注（45s）：指折线斜率，Langfuse显示记忆命中时token -18%。

## 第13页 实验C 工作台可观测性（新增）

- 设计：12故障×10被试，无工作台仅日志 vs 有工作台三栏，定位时间/准确率/轮次 + 性能阈值
- 结果：定位 418s→247s (-40%,p<0.001)，准确 44.2%→76.7% (+32.5%,p<0.001)，轮次 3.4→2.2；Graph p95 187ms<500ms，Inspector 94ms<300ms，SSE 890ms<2s
- 图占位：图7-5 箱线图 + 图7-6 动图与达标率（数据来源：埋点 + `graph_bench.py` 10k/50k 107ms）
- 结论：H3成立，可观测性显著提升调试效率

> 备注（60s）：这是答辩增量页，强调“阈值全达标”是工程可交付证据。

## 第14页 总结与展望

- 成果：双轨+M7+94%完成度，16路由15视图，35/35与压测达标，三实验p<0.05证实增益
- 不足：Neo4j云端依赖、多模态精度、20Goal/单用户样本、SSE多实例扩展
- 展望：本地小模型离线、移动端同构、100Goal真实A/B、GraphRAG混合检索与分层记忆

> 备注（45s）：成果一句话，不足诚实说三点，展望对应不足，给评委“可落地”印象。

## 第15页 致谢 & Q&A

- 致谢导师/评审/同学，GitHub与论文二维码
- 备份页（不计入15页）：ER图、API表、部署架构、Langfuse追踪截图

> 备注（15s）：致谢+“请批评指正”，准备高频问题：①为何6节点而非4节点 ②USE_PG双模权衡 ③工作台缓存一致性 ④记忆衰减参数依据 ⑤多模态幻觉控制。

---

## 附 演讲计时与材料清单

| 段 | 页 | 时长 |
|---|---|---|
| 开场 | 1-2 | 1.5分 |
| 技术与设计 | 3-8 | 5分 |
| 演示 | 9 | 2分 |
| 实证 | 10-13 | 4.5分 |
| 收尾 | 14-15 | 2分 |
| **合计** | 15页 | **15分** |

**图/数据来源清单**：所有图占位均注明数据来源为 `agent_run_log` / `stats/overview&trend` / `performance.now()` 埋点 / `scripts/*_bench.py` / Langfuse `trace_id`，确保可追溯。

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-30 | v0.4 | 新建15页大纲：每页≤5要点+备注，含工作台三栏动图占位与实验A/B/C三表p值、计时与问答预案 |
