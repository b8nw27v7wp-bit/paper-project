# TASK-BATCH-P1A — 核心 Agent 链路产品化

> 前置：`cd apps/server && python -m pytest tests/ -v --tb=short` 确认 35/35 全绿
> 工作目录：E:\paper project

---

## 任务1: 真实 LLM 推理链 — Planner 调 DeepSeek

修改: `apps/server/app/services/planner.py`

1. 重写 SYSTEM_PROMPT，要求输出严格 JSON 数组，每个任务包含 title/planned_start/planned_end/priority(1-5)/description/estimated_hours
2. 任务不能时间重叠，每天总时长不超过 hours_per_day，循序渐进
3. llm_generate 加 retry（JSON 解析失败重试 1 次）
4. 保留 mock_generate 作为 fallback
5. generate_plan 函数加入 thinking trace 到 SSE events（记录每步推理）
6. 验证：跑 `python -m pytest tests/test_plans.py -v` 确认不破

---

## 任务2: 真实 Embedding + 向量检索

修改: `apps/server/app/services/memory.py`

1. embed_text：确保优先调真实 embedding API，fallback 到 hash mock（已有，验证逻辑正确）
2. search_memory：
   - 删除子串匹配补偿（`if query in content: score = 0.85`）
   - 阈值调整：>0.7 高置信，>0.4 低置信可用
   - 加入记忆衰减：超过 30 天的记忆 score *= 0.7
3. 新增 auto 沉淀：任务完成时自动写入 memory_chunk（type=execution）
4. 验证：跑 `python -m pytest tests/test_memory.py -v` 确认不破

---

## 任务3: Agent ReAct 工具调用链

修改: `apps/server/app/agents/graph.py`, `apps/server/app/agents/state.py`

1. PlanState 改为 TypedDict，明确所有字段类型
2. researcher_node 改为 async，真正调用注册表工具：
   - 从 goal.title 提取关键词
   - 调 memory_search 检索相关记忆
   - 调 rag_search 检索相关知识
   - 调 graph_search 检索前置关系
   - 结果注入 state（memory/graphDeps/vectorDeps）
3. planner_node 接收 researcher 检索结果，在 LLM prompt 中注入上下文
4. 每个节点记录 thought trace（_thought 字段）
5. 验证：跑 `python -m pytest tests/test_agents_graph.py -v` 确认不破

---

## 完成后验证（必须全部通过）

1. `cd apps/server && python -m pytest tests/ -v --tb=short` → 35/35 passed
2. `python -c "from app.main import app; print('ok')"` → ok 无 warning
3. 汇报每项改动的具体内容
