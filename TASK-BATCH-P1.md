# TASK-BATCH-P1 — 核心 Agent 产品化（第一批大活）

> 目标：让系统从"骨架 mock"变成"真实可演示的 Agent 产品"
> 前置：先跑 `cd apps/server && python -m pytest tests/ -v --tb=short` 确认当前 35/35 全绿再开工

---

## 任务1: 真实 LLM 推理链 — Planner 真正调 DeepSeek

**现状**: `planner.py` 的 `llm_generate` 虽然写了真实调用，但 prompt 太简陋，输出解析脆弱
**目标**: Planner 能根据用户目标，调用 DeepSeek 生成结构化的 7 天学习计划

修改文件: `apps/server/app/services/planner.py`

具体要求:
1. 改进 SYSTEM_PROMPT，让它更专业：
   - 要求输出严格 JSON 数组
   - 每个任务包含 title, planned_start, planned_end, priority(1-5), description, estimated_hours
   - 任务之间不能有时间重叠
   - 每天总学习时间不超过用户设定的 hours_per_day
   - 任务要循序渐进，从基础到进阶
2. `llm_generate` 函数中，加入 retry 逻辑（JSON 解析失败重试 1 次）
3. 保留 mock_generate 作为 fallback（LLM 不可用时降级）
4. 加入 thinking trace：每次调用记录 "thought" 到 SSE events

---

## 任务2: 真实 Embedding + 向量检索 — 替换 hash mock

**现状**: `memory.py` 用 SHA256 hash 生成伪向量，`search_memory` 用子串匹配补偿
**目标**: 用真实的 text-embedding-3-small API 生成向量，用余弦相似度做真实检索

修改文件: `apps/server/app/services/memory.py`

具体要求:
1. `embed_text` 函数：确保优先调用真实 embedding API（已有代码逻辑，但需验证 fallback 行为）
2. `search_memory` 函数：
   - 删除子串匹配补偿逻辑（`if query and query in it.content: score = max(score, 0.85)`）
   - 改用真实的 numpy/cosine 计算（不依赖 numpy，手写即可）
   - 阈值调整：>0.7 为高置信，>0.4 为低置信但可用
3. 添加 `auto沉淀` 功能：用户完成任务后自动将执行记录写入记忆
4. 添加 `记忆衰减`：超过 30 天的记忆权重降低

---

## 任务3: Agent Graph 增强 — ReAct 工具调用链

**现状**: `graph.py` 的 researcher_node 只是列出工具名，不做真实调用
**目标**: Researcher 节点真正调用 memory_search/rag_search/graph_search 检索上下文，注入到 planner

修改文件: `apps/server/app/agents/graph.py`, `apps/server/app/agents/state.py`

具体要求:
1. `researcher_node` 改为 async，真正调用注册表中的工具：
   ```python
   async def researcher_node(state: PlanState) -> dict:
       # 1. 从 goal 中提取关键词
       # 2. 调用 memory_search 检索相关记忆
       # 3. 调用 rag_search 检索相关知识
       # 4. 调用 graph_search 检索前置关系
       # 5. 将结果注入 state
   ```
2. `PlanState` TypedDict 中明确所有字段类型
3. planner_node 接收 researcher 的检索结果，在 prompt 中注入上下文（citations）
4. 加入完整的 thought trace 记录每个节点的推理过程

---

## 任务4: RAG 知识库 — 真实的文档检索

**现状**: `rag/store.py` 只有存储，没有检索逻辑
**目标**: 实现完整的 ingest → chunk → embed → store → search 流程

修改文件: `apps/server/app/rag/store.py`, `apps/server/app/rag/chunk.py`, `apps/server/app/api/v1/rag.py`

具体要求:
1. `chunk.py`：实现文本分块（按段落/固定长度，overlap 50 tokens）
2. `store.py`：添加 `search_chunks` 函数，支持向量相似度检索
3. `rag.py` API：
   - POST /api/v1/rag/ingest — 上传文档，自动分块+嵌入+存储
   - GET /api/v1/rag/search?q=xxx — 检索相关知识片段
   - GET /api/v1/rag/chunks — 查看已有知识库
4. 支持 txt/md 格式文档上传

---

## 任务5: 知识图谱增强 — Neo4j 不可用时的 SQLite 图谱

**现状**: Neo4j 连不上就回退内存字典，重启就丢
**目标**: 用 better-sqlite3（Python 版）或 SQLAlchemy 存储图谱，保证持久化

修改文件: `apps/server/app/graph/neo.py`, 新增 `apps/server/app/graph/sqlite_graph.py`

具体要求:
1. 新增 SQLite 图谱存储（两张表：knowledge_nodes, knowledge_edges）
2. `neo.py` 改为：先尝试 Neo4j → 失败则用 SQLite 图谱 → 最后才回退内存
3. `add_triples` 支持从 RAG 文档中自动提取实体关系（简单的关键词匹配即可）
4. `search_prereqs` 支持多跳查询（BFS 2层）
5. API GET /api/v1/graph/subgraph?subject=xxx 返回子图

---

## 任务6: 记忆沉淀 + 自进化反思

**现状**: `scheduler/reflector.py` 和 `memory` 模块是空壳
**目标**: 用户完成任务后自动沉淀记忆，每周自动生成反思报告

修改文件: `apps/server/app/scheduler/reflector.py`, `apps/server/app/services/memory.py`, `apps/server/app/api/v1/reflection.py`

具体要求:
1. 任务完成时自动沉淀：
   - 执行时长、完成率、延迟原因 → 写入 memory_chunk (type=execution)
   - 如果完成率<0.5，额外记录"拖延"标签
2. `generate_reflection` 函数真正运行：
   - 统计本周完成率、拖延率、平均负荷
   - 分析模式（哪天效率高、什么类型任务容易拖延）
   - 生成下周 plan_patch（建议调整）
   - 写入 reflection_report 表
3. reflection API 返回真实的反思报告

---

## 完成后验证

1. `cd apps/server && python -m pytest tests/ -v --tb=short` — 全绿
2. `python -c "from app.main import app; print('ok')"` — 无 warning
3. 启动 server `python -m uvicorn app.main:app --port 8000` 能跑起来
4. 用 curl 测试核心流程：
   ```bash
   # 创建目标
   curl -X POST http://localhost:8000/api/v1/goals -H "Content-Type: application/json" -d '{"title":"学Python","deadline":"2026-09-01T00:00:00"}'
   # 生成计划
   curl -X POST http://localhost:8000/api/v1/plans -H "Content-Type: application/json" -d '{"goal_id":1,"preferences":{"hours_per_day":3}}'
   # 检索记忆
   curl http://localhost:8000/api/v1/memory/search?q=Python
   ```
5. 汇报每项改动和测试结果
