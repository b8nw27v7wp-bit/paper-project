# TASK-BATCH-P1B — RAG + 图谱 + 记忆反思

> 前置：P1A 已完成，35/35 全绿
> 工作目录：E:\paper project

---

## 任务1: RAG 知识库完整流程

修改: `apps/server/app/rag/chunk.py`, `apps/server/app/rag/store.py`, `apps/server/app/api/v1/rag.py`

1. chunk.py：实现文本分块（按段落分割，每块 500 字，overlap 50 字）
2. store.py：添加 search_chunks 函数，向量相似度检索，返回 top_k 结果
3. rag.py API：
   - POST /api/v1/rag/ingest — 上传 txt/md 文档，自动分块+嵌入+存储
   - GET /api/v1/rag/search?q=xxx — 检索相关知识片段
   - GET /api/v1/rag/chunks — 查看已有知识库列表
4. 验证：跑 test_rag_graph.py

---

## 任务2: 知识图谱 SQLite 持久化

修改: `apps/server/app/graph/neo.py`, 新增 `apps/server/app/graph/sqlite_graph.py`

1. 新建 sqlite_graph.py：两张表 knowledge_nodes(id,name,subject) + knowledge_edges(id,from_node,to_node,type)
2. neo.py 改为：Neo4j → SQLite 图谱 → 内存字典（三级 fallback）
3. add_triples 支持从文本中自动提取实体关系（简单关键词匹配）
4. search_prereqs 支持多跳 BFS（2层深度）
5. API GET /api/v1/graph/subgraph?subject=xxx 返回子图
6. 验证：跑 test_rag_graph.py

---

## 任务3: 记忆沉淀 + 自进化反思

修改: `apps/server/app/scheduler/reflector.py`, `apps/server/app/api/v1/reflection.py`

1. 任务完成时自动沉淀到 memory_chunk（type=execution），记录完成率/时长/延迟原因
2. generate_reflection 函数真正运行：
   - 统计本周完成率、拖延率、平均负荷
   - 分析模式（哪天效率高、什么类型容易拖延）
   - 生成下周 plan_patch（建议调整）
   - 写入 reflection_report 表
3. reflection API：GET /api/v1/reflection/latest 返回最新反思报告
4. 验证：跑 test_p2.py

---

## 完成后验证

1. `cd apps/server && python -m pytest tests/ -v --tb=short` → 全绿
2. `python -c "from app.main import app; print('ok')"` → ok
3. 汇报改动内容
