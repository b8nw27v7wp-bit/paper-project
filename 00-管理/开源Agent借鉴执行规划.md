# 开源Agent借鉴执行规划

> 版本：v0.1_20260830 | 00-管理 | 对应 SystemAgent `app/agents/system_agent.py:14` 与双轨 `WorkbenchView.vue:62`

## 1. 背景与目标

项目现 `基于多智能体协作与记忆增强的自进化学习任务规划与管理的智能体`，`SystemAgent studying-planner` 单点对外，内 `LangGraph 6节点` `app/agents/graph.py:497`，`37 passed` `3008 modules`。目标：借鉴 7 个开源Agent，按 `harness/可视化/协作/记忆/CLI` 五维补强，避免重复造轮子，论文第2章可直接引用。

## 2. 借鉴清单（按贴合度）

| # | 开源Agent | 借鉴点 | 落点 `file:line` | 价值 |
|---|-----------|--------|------------------|------|
| 1 | **Pi** `Pi/packages/agent` `Pi/packages/ai` | `harness/session/memory.ts` 双写+`compaction/summarize`，`tool before/after hooks`，`UnifiedClient fallback链` | `app/services/planner.py:10` `PlanStore` 已借 `FileMemorySaver`；深借 `app/agents/tools/registry.py:36` `BeforeToolCallResult/AfterToolCallResult` 细粒度校验与 `AgentEventType` 结构化事件 | harness 成熟度最高，已在仓 `Pi/`，成本 0 |
| 2 | **LangGraph Studio / LangSmith** | 6节点 DAG 可视化、checkpoint 时光回放、trace 检索 | `apps/frontend/src/views/WorkbenchView.vue:62` `GraphCanvas.vue:39` `GET /api/v1/agent/manifest:13`；`app/core/checkpoint.py:1` `FileMemorySaver` | 调试效率，论文图 5.1 可直接截图 |
| 3 | **AutoGen** `ConversableAgent/GroupChat` | `Speaker Selection` 与 `cost` 统计 | `app/agents/graph.py:251` `researcher gather`；`app/services/stats.py:68` `llm_cost = total*0.002` 可升级为 token 级 `completion_tokens` | 协作调度更精细，成本可观测 |
| 4 | **CrewAI** | `Role/Task expected_output` 显式化 | `app/agents/tools/registry.py:275` `ToolSchema` `label/description/required`；`app/agents/tools/registry.py:84` `RegisteredTool` | 规范工具契约，论文 2.2 可对比 |
| 5 | **OpenDevin/OpenHands** | `event: thought/action/observation` 三件套与 `micro-agent` 复用 | `app/api/v1/plans.py:251` 8事件 `thought/tool_call*/task_created` 已对齐，借其 `event stream` 持久化 | 事件模型标准化，便于 `studying trace` 复盘 |
| 6 | **MemGPT/Letta** | 分级记忆 `core/recall/archival` + `self-directed` 摘要 | `app/services/memory.py:84` 三级阈值 `0.7/0.4` 可升级为 `STM(10轮)/LTM(pgvector)` + `AS` 定时 `22:00` | 记忆增强论文深度 |
| 7 | **Aider/Continue** | `repomap` + `diff apply` 闭环 | `apps/cli/main.py:23` `Typer+Rich` `studying` 已 `studying planner`，借 `aider` 的 `apply patch` 于 `apps/frontend/src/components/TaskDrawer.vue` | CLI 编辑闭环，答辩演示 |

不荐：`MetaGPT SOP` 过重不贴教育规划；`CAMEL` 偏纯对话。

## 3. 执行规划（4周，单人）

### W1：Pi harness 深借 + 可视化（P0）
- **任务**：`registry.py:36` 补 `ToolSchema.validate` 单测 5例；`planner.py:10` `compaction.should_compact/summarize` 接 `Pi` 阈值（事件>16 条）；`checkpoint.py:1` 加 `get_state` 时光接口 `GET /agent/state?trace_id`。
- **产出**：`tests/test_registry_compaction.py` 5 passed，`Workbench` 增加 `History` 滑杆回放。
- **验收**：`pytest 38 passed`，`Graph` 点击穿透 `<100ms` 保持。

### W2：协作与成本（P1）
- **任务**：`graph.py:251` 引入 `AutoGen` 的 `cost` 回调，`stats.py:68` `llm_cost` 从 `*0.002` 升级为 `token*price`（`UnifiedClient` 返回 `usage`）；`graph.py:482` `should_replan` 加 `cost>阈值` 熔断。
- **产出**：`DashboardView.vue` 新增 `Cost` 折线，`stats/overview` 返回 `completion_rate/delay_rate/llm_cost` 三件。
- **验收**：`POST /agent/plan` 返回 `usage`，`Dashboard` 可观测。

### W3：记忆分级（P1）
- **任务**：`memory.py:84` 升级为 `STM(内存10轮, LRU)` + `LTM(pgvector HNSW m=16)` + `AS` 定时摘要，复用 `MemGPT` 的 `archival` 策略；`ab_test_memory` 补 `STM vs LTM` 对照。
- **产出**：`RFC: 记忆分级设计.md`，`pgvector_bench 500 p95 <120ms` 保持。
- **验收**：有/无记忆 `7日完成率 +15%` 实验可复现。

### W4：CLI 闭环（P2）
- **任务**：`apps/cli/main.py:29` `studying` 借 `aider repomap` 为 `TaskDrawer.vue` 提供 `diff preview`，`studying trace` 支持 `apply patch`。
- **产出**：`studying plan --apply` 一键写回 `Task`，`e2e/workbench.spec.ts:158` 补 `apply` 用例。
- **验收**：`studying --help` 含 `agent/project/trace/apply`，`npm run build` <7s。

## 4. 风险与取舍

- **Pi 深入**：`Pi` 为 `Bun` 生态，`TS` 类型与 `Python` 需翻译，限 `harness` 层，不深入 `coding-agent`。
- **LangSmith 依赖**：`LangSmith` 需 `apiKey`，本地 `FileMemorySaver` 为主，`LangSmith` 为可选上报。
- **成本**：`DeepSeek-V3` 0.002/任务为估算，`W2` 后接真实 `usage` 需 `ZHIPU_API_KEY`，无 key 时回退估算不阻塞 CI。

## 5. 交付与论文映射

- **文档**：本规划即 `00-管理` 输入，`04-论文/02-相关技术.md` 2.2 节直接引用 7 Agent 对比表。
- **代码**：`app/agents/system_agent.py:14` `SystemAgent` 为总入口，`W1-W4` 各 1 个 `PR`，每 `PR` `pytest 37` + `vue-tsc 0` + `vite 7s` 门禁。
- **演示**：`studying` CLI + `Workbench` 三栏 + `Graph` 回放，答辩 `3分钟` 可串联。

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-30 | v0.1 | 初版 7 Agent 借鉴 + 4周执行规划 |

