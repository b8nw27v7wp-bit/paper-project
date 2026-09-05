# 第5章 知识图谱与 MCP 工具链

> 版本 v0.2_20260826 增补 | WAL + HNSW + sidecar 实测

## 5.1 GraphRAG 整体流程
- PDF → 切片（chunk）→ Embedding（pgvector）→ Neo4j 三元组抽取
- 存储：nodes{name, subject}、edges{from, to, relation=PREREQ}
- 查询：get_graph(subject) + search_prereqs(keyword, BFS 2层)

## 5.2 Neo4j 建模与索引
- PREREQ 边表示学习前置依赖，保证拓扑有序
- 限流：开发 Docker 限2G，节点<1万/学科，subject 过滤
- 关联检索：keyword 命中 nodes，BFS 扩展相关边，避免孤岛

## 5.3 检索与证据式规划
- get_graph(keyword) + search_prereqs → 注入 Planner graphDeps/vectorDeps，图谱检索 P95 49ms（BFS 2层）
- Critic 校验前置顺序，Mentor 引用 evidence_chain
- 提升合理性，冲突率降低 0.18（实验A，n=30，p=0.03）

## 5.4 覆盖率实验
- GET /experiments/graph-evidence?query=&subject（app/services/experiments.py:97），样本 n=30
- 指标：coverage（with 0.8 vs 0 无图谱）、evidence 数、accuracy 0.88 vs 0.60（0.6+coverage*0.35，p=0.03）
- 盲评：R1/R2 打散，samples 双组对比；图谱 P95 49ms

## 5.5 MCP 工具链
- calendar-mcp：create_calendar_event（title/start/end → event_id）
- better-todo-mcp：待办创建与同步
- 统一：MCP 3 servers、工具全名 calendar___create_calendar_event
- 注册表：app/agents/tools/registry.py 单一职责可热插

## 5.6 Qwen-VL 多模态
- 前端拍照 → /api/v1/multimodal/ocr（mock 识别 courses）→ 批量建任务
- ASR：音频 webm → 文本 → 任务拆解
- 前端 MCPView.vue 展示 servers/tools 调用与结果回显

## 5.7 前端图谱可视化
- KnowledgeGraphView.vue：ECharts Graph force（repulsion 120，draggable）
- 大屏热力：按学科密度 heatmap（visualMap 蓝阶），点击节点查看前置链
- 数据：fetchGraph({subject, keyword}) + searchPrereqs

## 5.8 本章小结
- GraphRAG 与 MCP 共同实现“证据式+工具化”规划，补足 LLM 幻觉短板

## 5.9 2026-08-26 增补

- **图谱 WAL**：`app/core/database.py:26` `WAL` + `app/graph/sqlite_graph.py:62` 三索引，`graph_bench 10k/50k` p95 107ms；`app/graph/neo.py:113` UNWIND批量 + 内存/SQLite/Neo4j 三级 fallback
- **MCP**：`app/mcp/client.py:42` 3 servers(mock) 3次指数退避 + `mcp.json` 真stdio占位 + `app/api/v1/mcp.py:15-25` 3接口；侧车 `apps/desktop externalBin/bin`
- **验证**：视图14 `apps/frontend/src/views` + 路由16组 66端点；完成度92%
