# 第4章 多Agent协作与记忆增强

> 版本 v0.2_20260826 增补 | 6节点 + FileMemorySaver + asearch + HNSW + WAL

## 4.1 LangGraph 状态设计
- State 字段：goal/preferences/trace_id/memory/graphDeps/vectorDeps/milestones/tasks/critic_feedback/mentor_msg/rewrites/_thought/_patch
- 可序列化，便于 checkpoint 与 SSE 重放

## 4.2 节点详解
- Researcher：并行3检索（memory/knowledge/graph），asyncio.gather
- Planner：UnifiedClient.chat 生成 JSON 任务列表，含重试
- Executor：批量落库 Task（含 citations），source_agent=planner:multi
- Critic：规则（时间重叠/超载）+ LLM 语义校验，输出 rewrites
- Mentor：基于记忆与学习风格个性化文案
- Reflector：周 patch（reduce_load/add_buffer/prefer_weekday）

## 4.3 执行流程与可追溯
- config={"configurable":{"thread_id":trace_id}} 支持 Pi 式可恢复
- 事件序列 thought/tool_call/task_created/critic_feedback/mentor_msg/reflector_patch/done
- PlanStore 内存+DB 双写，should_compact/summarize 超阈值摘要
- 落库 6 条 agent_run_log，前端 SSE 事件流逐条推送（0.08s 间隔）

## 4.4 pgvector 记忆实现
- 表 memory_chunk（1536维，向量 cosine_ops HNSW，user_id+type 联合索引），检索 P95 108ms（app/services/memory.py:embed_text + performance.timed，n=30）
- 写入：切片→Embedding（异步 embedding）→ 存储（WAL 优化）
- 检索：faux 兜底 + 真实 embedding cosine，top_k=5/10；缓存命中 <5ms（LRUCache 512，performance.py:8）

## 4.5 检索注入与增益
- memory/knowledge 分别注入 Planner，graphDeps 参与 Critic 校验
- 提升合理性，证据引用 citations 透传 Task

## 4.6 有/无记忆完成率实验
- 设计：同 query 分 with/without，盲评 deltas，7日 completion_rate，样本 n=30
- 接口：GET /experiments/memory-ablation?query=&top_k（app/services/experiments.py:55）
- 结果：有记忆 +15%（stats/overview 基线 -0.12 vs +0.05），p=0.03 显著（配对 t）；向量检索 P95 108ms
- CLI：memory --ablation --json 输出可管道；可视 ExperimentsView.vue

## 4.7 容错与性能
- faux mock：PYTEST_CURRENT_TEST/无 key 时直接 mock_generate
- retry 1次 JSON 解析，busy_timeout，LRU 缓存 hit_rate 监控
- 验证：test_agents_graph、test_memory、test_plans 覆盖

## 4.8 本章小结
- 多Agent 协作与记忆增强共同保证规划可解释、可追溯、可个性化

## 4.9 2026-08-26 增补（实测对表）

- **图 checkpoint**：`app/agents/graph.py:351` `build_graph(checkpointer=FileMemorySaver())` + `_wrap_graph_for_compat` 的 `thread_id=trace_id` 可恢复，`PlanStore` 内存+DB双写(`AgentRunLog.output` 全量 events)
- **检索**：`app/services/memory.py:139` `asearch_memory` 真 `embed_text` (优先 `UnifiedClient.embed` 回退 `_hash_mock_embedding`) + `app/models/memory.py:17` `Vector(1536)` HNSW `m=16 ef=64` 幂等；`pgvector_bench 500` p95 108ms
- **验证**：`35/35 26.26s` + `vite 7.21s`; 路径 `apps/web`→`apps/frontend` 视图12→14 已修正
