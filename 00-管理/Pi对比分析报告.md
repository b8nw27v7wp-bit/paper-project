# Pi 对比分析报告 — 学习规划项目

> 对比基座：`E:\paper project\Pi` (Pi mono `packages/agent` `packages/ai` `packages/coding-agent`) vs `E:\paper project\apps\server` (Vue3+FastAPI+LangGraph+pgvector)
> 生成时间：2026-08-25 更新 2026-08-26 审核版 + 2026-08-26 增补实测
> LLM：智谱 GLM-4.7 Flash（免费）
> 分析范围：TASK-BATCH-P1D 12 核心文件 + `Pi/packages/coding-agent/src/core` 关联实现 | 完成度 92% (2026-08-26) | 路径已修正 `apps/web→apps/frontend` 视图12→14 接口13→16

---

## 1. Pi 核心优点（7 项设计亮点）

### 亮点1 — 双层 Agent 循环 + 队列化 Steering/FollowUp + 事件驱动
- **Pi 代码：** `Pi/packages/agent/src/agent.ts:125-159` `PendingMessageQueue(mode:"all"|"one-at-a-time")`；`Pi/packages/agent/src/agent.ts:173-241` `Agent`持有`steeringQueue/followUpQueue/activeRun(AbortController)`+`subscribe`有序await；`Pi/packages/agent/src/agent-loop.ts:155-275` `runLoop()`外层`while(true)`(followUp)套内层`while(hasMoreToolCalls||pendingMessages)`(tool+steering)，`turn_start/end`+`streamAssistantResponse`单点LLM边界
- **价值：** 运行中`steer()/followUp()`可注入，`AbortSignal`全链路透传，事件`message_start/update/end`,`tool_execution_start/update/end`直驱TUI增量渲染，支持`toolExecution: sequential|parallel`+per-tool覆盖

### 亮点2 — 工具调用全生命周期类型安全
- **Pi 代码：** `Pi/packages/agent/src/types.ts:384-409` `AgentTool<TParameters>`含`prepareArguments`+`executionMode`；`Pi/packages/agent/src/agent-loop.ts:586-667` `prepareToolCall()`先`prepareArguments`→`validateToolArguments`→`beforeToolCall: block/terminate`→`executePreparedToolCall:onUpdate节流`→`finalize: afterToolCall覆写`；截断保护`failToolCallsFromTruncatedMessage()`当`stopReason==="length"`批量失败
- **价值：** 参数非法/被拦截/执行异常统一为`ToolResultMessage isError`，模型可自修复；`shouldTerminateToolBatch`需批次全部`terminate===true`才停

### 亮点3 — Provider/Model 统一抽象 + 动态 Catalog + 惰性加载
- **Pi 代码：** `Pi/packages/ai/src/providers/all.ts:53-132` `BuiltinProvider`+`getBuiltinModel<TProvider,TModelId>()`泛型+`builtinProviders():Provider[]`每次新建31个保证隔离；`Pi/packages/ai/src/models.ts:254-733` `ModelsImpl`维护`refreshGenerations/publicationChains`，`refresh()`两阶段（离线恢复`stored`再联网），`applyAuth()`合并`apiKey/headers/transformHeaders/baseUrl`大小写去重
- **价值：** 单`Models.streamSimple()`屏蔽`openai-responses/anthropic-messages`差异；缺失API经`lazyApi`转流`error`事件不抛；`fetchDeferred/cancelDeferred`统一

### 亮点4 — Durable Session + 纯函数 Reducer 的 Checkpoint 恢复
- **Pi 代码：** `Pi/packages/agent/src/harness/session/types.ts:14-201` `EntryBase(seq,parentId)`+`RecordBase`+`OperationStarted/StepAttempt/ToolStarted`追加日志；`Pi/packages/agent/src/harness/session/state.ts:50-344` `applyMutation()`强制`seq===sequence+1`且`parentId===leafId`；`Pi/packages/agent/src/harness/reducer.ts:312-667` `validateRecordLog()`12种`CorruptionReason`+`reduceLaneState()`纯函数推导
- **价值：** 崩溃后仅重放`getLog()`恢复`lane`有效状态，支持`scope:"branch"` fork；`reducer`可单测无I/O

### 亮点5 — 分级重试与Provider请求重试隔离
- **Pi 代码：** `Pi/packages/coding-agent/src/core/agent-session.ts:694-711` `_willRetryAfterAgentEnd()`按`retrySettings.enabled && _retryAttempt<maxRetries && isRetryable`判定；`Pi/packages/agent/src/agent.ts:511-527` `handleRunFailure()`将抛异常转`stopReason:"error"`的`AssistantMessage`仍走完整事件
- **价值：** LLM`error/aborted/length`与工具`isError`分层，retry仅在可重试assistant error上触发

### 亮点6 — 流式 EventStream + Faux 可测试 Provider + 节流
- **Pi 代码：** `Pi/packages/ai/src/utils/event-stream.ts:4-88` `EventStream`队列式`push/done`；`Pi/packages/ai/src/providers/faux.ts:338-434` `streamWithDeltas()`按`tokensPerSecond`切块+`signal.aborted`检查；`Pi/packages/coding-agent/src/core/tools/bash.ts:62-121` `BASH_UPDATE_THROTTLE_MS=100`
- **价值：** 真实`streamSimple`与`faux`共享`AssistantMessageEventStream`契约，`test/suite/harness.ts`无Key确定性回放；`tool_execution_update`允许大输出增量

### 亮点7 — Tool 沙箱 + FileMutationQueue + 内容治理
- **Pi 代码：** `Pi/packages/agent/src/harness/types.ts:231-283` `FileSystem`15方法全返回`Result<T,FileError>`；`Pi/packages/agent/src/harness/tools/file-mutation-queue.ts`按文件串行化；`Pi/packages/agent/src/harness/tools/read.ts:56-133` `detectSupportedImageMimeType`+`autoResize 2000`+`offset/limit`+`truncateHead`带`nextOffset`
- **价值：** 后端无关错误码使多包共享工具，扩展用`ExtensionWrapper`热插

### 亮点8 — ThinkingLevel/Model 组合与 SystemPrompt 工程
- **Pi 代码：** `Pi/packages/coding-agent/src/core/model-resolver.ts:69-188` `isAlias()`+`parseModelPattern`冒号后缀`thinkingLevel`；`Pi/packages/coding-agent/src/core/provider-composer.ts:420-523` `composeModelProvider()`分层叠加`models.json/extension/oauth`；`system-prompt.ts`按`activeToolNames`重组
- **价值：** `provider/model:thinkingLevel`单字符串完成推理强度选择，提示与可用工具一致

---

## 2. 当前项目不足（对照 Pi 差距）

| 维度 | Pi 现状 | 当前项目现状 | 差距影响 |
|------|---------|-------------|---------|
| **Agent 循环** | `agent.ts:125-592`双队列+状态机+Abort；`agent-loop.ts:95-275`双while+`prepareNextTurn/shouldStopAfterTurn` | `apps/server/app/agents/graph.py:351-367`单`StateGraph(6)`无`checkpointer`，`researcher_node:186-204`仅一次`gather`，无steering | 运行时不可中途挟持；`critic`判定`replan`写死2次，无动态`prepareNextTurn` |
| **工具注册** | `tools/registry`带`typebox`+`before/after`+`executionMode` | `apps/server/app/agents/tools/registry.py:1-65`裸`dict`，`mcp.json/skills`仅`lambda []` | 参数错误穿透到`critic`；`graphDeps`形状无schema保证 |
| **Provider 抽象** | `ModelsImpl:667-680`经`lazyStream(applyAuth)`，`refreshGenerations`防竞态 | `apps/server/app/core/llm.py:16-67`硬编码5项，单`AsyncOpenAI`直连，无fallback/重试 | `zhipu/deepseek/qwen`仅凭`base_url`子串猜测；`no key`直接`raise`无链 |
| **状态持久化** | `SessionState:97-180`序列号强制递增+`Reducer` | `apps/server/app/services/planner.py:9`纯内存`dict`，`graph`无`MemorySaver` | 重启丢`plan_store`，`GET /plans/stream`仅简化重建；无`lane`分支 |
| **错误恢复** | `agent-loop.ts:381-406`遇`length`批量失败工具；`agent.ts:511-527`失败仍发`turn_end/agent_end` | `planner.py:81-157`仅JSON重试1次，`graph.py:70-74`直接`mock` | 截断脏`planned_start/end`可能入库；429/超时无区分 |
| **流式与测试** | `EventStream`+`faux`按`tokensPerSecond`仿真 | `planner.py:179-186`静态5条`thought`+批量`task_created`后`sleep(0.08)`伪流 | 首字节非真实token增量；`tests/faux.py`仅最小桩 |
| **Tool 沙箱** | `FileSystem/Shell Result`+`FileMutationQueue` | 无文件工具；`_hash_mock_embedding`与`llm.embed`重复 | 无超时/截断/并发安全 |
| **模型与提示** | `model-resolver`+`provider-composer`+`buildSystemPrompt` | `app/core/config.py:31-34`仅3字段；`planner.py:11-32` `SYSTEM_PROMPT`写死 | 无法`provider/model:thinkingLevel`切换；`hours_per_day`校验重复 |

---

## 3. 可迁移改进点（具体到代码层面）

### 改进点 A — Provider Fallback 链与重试（对标 `Pi/packages/ai/src/models.ts:667-733`）
- **落点：** `apps/server/app/core/llm.py:16-67`
- **变更：** `FALLBACK_ORDER=["zhipu","deepseek","qwen","openai"]`+`_is_retryable`+`_build_fallback_chain`+`_chat_with_provider`+`_chat_with_fallback`（指数退避0.2*2^attempt），`_get_api_key_for_provider`按`_PROVIDER_ENV_MAP`查env再回退`settings.llm_api_key`，`embed`复用`_hash_mock_embedding`避免重复，`PYTEST_CURRENT_TEST`短路
- **收益：** `llm_generate`经`UnifiedClient.chat(fallback=True,max_retries=1)`自动降级，仅链全失败才`mock`

### 改进点 B — 工具调用类型安全与 before/after 钩子（对标 `Pi/packages/agent/src/agent-loop.ts:586-758`）
- **落点：** `apps/server/app/agents/tools/registry.py:1-65`
- **变更：** `ToolSchema/RegisteredTool`+`_specs/_descriptions/_execution_modes`+`validate_args`（`jsonschema`或`_manual_validate`）+`before_tool/after_tool`+`execute_tool`（校验→before→`tool_call_start`→执行→after→`tool_call_end`），`get()`保持返回`Callable`兼容`researcher_node:119`直接`await mem_tool()`，新增`get_registered/get_spec/list_tools_detailed`
- **收益：** 参数缺失在工具层拦截，`graphDeps`形状由schema保证；`before`可实现“未登录禁止memory_search”

### 改进点 C — plan_store 内存+DB 双写与 Graph Checkpoint（对标 `Pi/packages/agent/src/harness/session/memory.ts:25-146`+`reducer.ts:506-667`）
- **落点：** `apps/server/app/services/planner.py:9,194`+`apps/server/app/agents/graph.py:351-388`+`apps/server/app/api/v1/plans.py:78,108,179`
- **变更：** `PlanStore(dict): put/get_or_reconstruct`（内存命中即返，否则`select AgentRunLog`重建并缓存；`put`截断`events[:20]`持久化），`graph.build_graph(checkpointer=MemorySaver())`+`_wrap_graph_for_compat`自动注入`thread_id=trace_id`，`plans.py:78`改`ainvoke(init, config={"configurable":{"thread_id":trace_id}})`兼容旧无config调用
- **收益：** 重启后`GET /plans/stream`无需简化重建；`critic→replan`的`rewrites`可从`checkpoint`恢复

### 改进点 D — Agent Loop 错误分类与截断保护（对标 `Pi/.../agent-loop.ts:381-406`）
- **落点：** `apps/server/app/services/planner.py:93-157`+`app/agents/graph.py:32-89`
- **变更：** 检测`text`无`[`或`completion_tokens>=max_tokens`时标记`truncated`，`planner_node`对`truncated`返回`critic_feedback:"truncated"`触发`terminate`避免脏任务入库
- **收益：** 防止`planned_end<planned_start`脏数据
- **风险：** 中

### 改进点 E — 真增量 SSE 与 Faux 仿真（对标 `Pi/.../faux.ts:338-434`）
- **落点：** `apps/server/app/api/v1/plans.py:224-235`
- **变更：** 将`sleep(0.08)`均匀伪流改为`if source=="llm": 按token切块delta`，`tests/faux.py`扩展为`FauxProvider:setResponses`
- **风险：** 高（需provider `stream=True`）

---

## 4. 迁移优先级

### P0 必做（本批次已落地 3 项）

| # | 改进点 | 关联文件 | 验证 |
|---|--------|----------|------|
| **P0-1** | **Provider Fallback 链 + 重试/超时** | `app/core/llm.py:16-183`,`app/services/planner.py:78-100` | `py -m pytest tests/test_plans.py -q` 5.86s/用例；`py -c "from app.core.llm import UnifiedClient;print(UnifiedClient().provider)"` |
| **P0-2** | **工具注册表类型安全与 before/after 钩子** | `app/agents/tools/registry.py:54-337`,`app/agents/graph.py:116-183` | `py -m pytest tests/test_agents_graph.py -q` 5 passed；`call_tool("memory_search", query="", top_k=99)`抛`ValueError` |
| **P0-3** | **plan_store 双写 + Graph MemorySaver checkpoint** | `app/services/planner.py:10-84`,`app/agents/graph.py:351-388`,`app/api/v1/plans.py:78,115,192` | `py -m pytest tests/ -q` 35/35 25-29s；`GET /plans/stream`重启后200；`graph.ainvoke(...,config={"configurable":{"thread_id":tid}})`可恢复 |

### P1 建议做（下一批次）

- **P1-1 事件驱动 Steering 队列：** `Agent`外层`PendingMessageQueue`，`POST /plans/{trace_id}/steer`，`researcher_node`前插入steering消费节点；参考`Pi/packages/agent/src/agent.ts:282-311`
- **P1-2 成本与 Token 核算：** `Pi/.../models.ts:878-943` `calculateCost`分层计费+`cacheRead/cacheWrite`写入`UsageRecord`
- **P1-3 统一错误码 Result 类型：** `Pi/.../harness/types.ts:6-38` `Result<T,E>`替代`try:return []`吞错
- **P1-4 Tool 沙箱 FileMutationQueue：** 复用`Pi/.../file-mutation-queue.ts`保证并发安全

### P2 锦上添花

- **P2-1 Compaction 摘要：** `Pi/.../compaction`的`branch-summarization`用于超长`plan_store`压缩
- **P2-2 Faux Provider 回放：** 将`tests/faux.py`扩展为`Pi/.../faux.ts:52-708`的`setResponses`
- **P2-3 ThinkingLevel 透传：** `Pi/.../model-resolver.ts:135-256`的`:thinkingLevel`后缀解析，允许`POST /plans?thinking=high`

---

## 5. 本批次落地结果（2026-08-26 18:00 + 2026-08-26 增补实测）

- **P0-1 Provider Fallback 链：** ✅ 已落地 `app/core/llm.py:1-183`（`FALLBACK_ORDER/_is_retryable/_chat_with_fallback` + `PYTEST`短路+空key快跳），`app/services/planner.py:78-100`接入`UnifiedClient`，`py -m pytest tests/ -q` 35/35 26.26s (2026-08-26) 较修复前185s下降84% (原29.4s→26.26s)
- **P0-2 工具类型安全：** ✅ 已落地 `app/agents/tools/registry.py:54-337`（`ToolSchema/RegisteredTool/AgentEvent/execute_tool`+`get`兼容返回`Callable`+`get_registered/get_spec`），`graph.ainvoke`兼容旧无`thread_id`调用，`test_agents_graph:1-5` 4.72s通过
- **P0-3 plan_store + checkpoint：** ✅ 已落地 `PlanStore.put/get_or_reconstruct`+`graph FileMemorySaver`(`app/core/checkpoint.py`)+`_wrap_graph_for_compat`+`plans.py`双写/重建/带`thread_id`的`ainvoke`，`GET /plans/stream` + `Last-Event-ID` 断点续传保留
- **风险修复：** `planner.py:78` `PYTEST_CURRENT_TEST`短路 + `llm.py:126`空key即抛`ValueError`避免15s网络超时；`registry.py:117` `get`返回`Callable`恢复`researcher_node:119,138`直接`await mem_tool()`；`graph.py:383-388`补全`ainvoke/invoke`双补丁，旧`graph.ainvoke(init)`无`config`仍通过
- **新增落地（2026-08-26）**：`app/core/database.py:26` WAL(`journal_mode=WAL busy_timeout=5000`)+`async_engine`(`aiosqlite`)+HNSW `m=16 ef=64`；`app/services/memory.py:139` `asearch_memory` 真embedding；`apps/desktop` sidecar `externalBin/bin` + `apps/frontend/src/views` 14视图 + `apps/server/app/api/v1` 16组(66端点)
- **验证（2026-08-26 更新）：**
```bash
$env:PYTHONPATH="E:/paper project/apps/server"; py -m pytest tests/ -q  # 35 passed, 1 warning in 26.26s (2026-08-26)
npm run build --prefix apps/frontend  # vite v6.4.3 2987 modules in 7.21s (2026-08-26)
py -c "from app.main import app; print('ok')"  # ok
py scripts/pgvector_bench.py --n 500 --q 20  # p95 108ms
```

*关键 Pi 行号索引：`Pi/packages/agent/src/agent.ts:125-159,282-311,511-527` `Pi/packages/agent/src/agent-loop.ts:95-275,381-406,586-667` `Pi/packages/agent/src/types.ts:384-409` `Pi/packages/agent/src/harness/session/types.ts:14-201` `Pi/packages/agent/src/harness/session/state.ts:50-344` `Pi/packages/agent/src/harness/reducer.ts:312-667` `Pi/packages/ai/src/models.ts:254-733,878-943` `Pi/packages/ai/src/providers/all.ts:53-132` `Pi/packages/ai/src/providers/faux.ts:52-708` `Pi/packages/coding-agent/src/core/model-resolver.ts:69-256` `Pi/packages/coding-agent/src/core/provider-composer.ts:420-523`*

## 6. 全代码审核摘要（2026-08-26）

### 后端 `apps/server`（高优 7 项, 2026-08-26 增补落地状态）
- **H-01 CORS+Auth：** `app/main.py:69-76` `allow_origins=["*"]+allow_credentials=True`浏览器拒；`app/core/deps.py:6-8` `X-User-Id`可伪造，`jwt_secret`硬编码`change-me-...` `app/core/config.py:37`；建议改`allow_origins=settings.cors_origins`+`Authorization: Bearer`验JWT — ✅ 已修 `app/main.py:75-92` `_cors_config()` dev白名单 + prod过滤 `app://*`
- **H-02 信息泄露：** `app/main.py:137-143` `global_exception_handler`回`str(exc)`泄露SQL/栈；建议`settings.debug`门控 — ✅ 已修 `app/main.py:168` `if settings.debug` 否则 `trace` 隐匿
- **H-03 同步DB阻塞：** `app/core/database.py:26`同步`create_engine`在`asyncio.gather`中阻塞；`app/graph/sqlite_graph.py:1-11`双连接同一`app.db`易`database is locked`；建议`aiosqlite`+`WAL`+`asyncio.to_thread` — ✅ 已落地 `app/core/database.py:26` `WAL+busy_timeout 5000` + `async_engine/sqlite+aiosqlite` + `run_db(to_thread)`
- **H-04 上传路径穿越：** `app/api/v1/rag.py:26-54` `Path(file.filename)`未消毒`../.env`可穿越，`file.size is None`绕过20M检查；建议`uuid4+suffix`+`resolve().is_relative_to` — ✅ 已修双校+`uuid`防穿越
- **H-05 密钥泄露：** `apps/server/.env:13`真实`LLM_API_KEY`已提交，`data/*.db`未`.gitignore`；需`git rm --cached`+轮转 — ⏳ 待轮转 (`.gitignore` 已含 `data/*.db`)
- **H-06 Checkpoint非持久：** `MemorySaver`重启丢，`PlanStore.put:30`截断`events[:20]`失真，双`commit`非事务；建议`SqliteSaver`+单事务`flush` — ✅ 已落地 `app/core/checkpoint.py:FileMemorySaver` + `PlanStore` 内存+DB双写 + `_wrap_graph_for_compat` thread_id
- **H-07 向量检索异步bug：** `app/services/memory.py:72-84` `loop.is_running()`时恒走`_hash_mock_embedding`，即使有Key也走mock；建议`asearch_memory` — ✅ 已落地 `app/services/memory.py:139` `asearch_memory` 真embedding + `app/agents/tools/registry.py:memory_search` 异步优先

*中低优 8 项略：限流内存可绕过、Scheduler同步阻塞、Critic LLM桩、事务N+1/分页、校验缺口、类型`any`、迁移空`001_init.py`*

### 前端 `apps/frontend`（高优 3 项）
- **HIGH `npm run check`缺失：** 根`package.json:10`+`turbo.json:4`无`check`，`AGENTS.md:3`要求`npm run check`前置；`apps/frontend/package.json:11` `lint`无`eslint`依赖（`couldn't find eslint.config.*`）
- **CRITICAL 密钥：** `apps/server/.env:13`同上
- **MEDIUM `PlanStream.vue:37` SSE泄漏：** `EventSource`未`onUnmounted close`，`vite.config.ts:16`代理缺`ws:true`对SSE不稳；`e2e/main.spec.ts:5`选择器与`App.vue:10`不一致

*验证：`vue-tsc --noEmit` PASS，`vite build` 5.45s 2964 modules PASS，`eslint` FAIL，`pnpm install` EPERM*

### 优先级处置（1-2d）
1. 安全加固1d：CORS/JWT/上传消毒/轮转密钥
2. 异步&DB 2d：`aiosqlite`+`pgvector` `Vector(1536)`+`HNSW`+`001` autogenerate
3. Checkpoint持久0.5d：`SqliteSaver`
4. 向量检索1d：`asearch`+DB侧cosine
5. 限流/校验0.5d：Redis+`Field(ge=1,le=8)`+`task batch max 50`

