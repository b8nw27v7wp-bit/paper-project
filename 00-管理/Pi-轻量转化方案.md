# Pi 轻量设计转化方案 — 融入本项目

> 学习对象: `E:\paper project\Pi` (earendil-works/pi, 4工具极简) | 转化目标: 任务规划Agent更轻、可插拔、provider无关 | 版本 v0.1_20260823

## 1. Pi 轻量精髓 (提炼)

| Pi 设计 | 要点 | 代码落点 `Pi/packages/*` |
|---------|------|--------------------------|
| **4工具极简** | `read/write/edit/bash` 单一职责，系统提示<1000 tokens，易扩展 | `agent/src/harness/tools/index.ts` |
| **统一LLM** | `pi-ai` 20+ provider (Anthropic/OpenAI/Google/xAI/DeepSeek) /login BYOK | `ai/src/*` `models.generated.ts` |
| **自扩展** | 运行时 `Extensions/Skills/Templates` TS自注册 | `agent/src/harness/skills.ts` |
| **会话** | `compaction/branch-summarization` 自动压上下文 | `harness/compaction/*` |
| **无内置权限** | 依赖容器化 (Gondolin/Docker/OpenShell) | `coding-agent/docs/containerization.md` |
| **质量** | `no any` `top-level import` `erasable TS` `npm run check` | `AGENTS.md` |

## 2. 对表本项目 (差距)

| 本项目现状 | Pi 启示 | 差距 |
|------------|---------|------|
| 6节点Graph (planner/researcher/...) 每节点各自调LLM | 4工具+1提示，工具可插拔 | 节点偏重，需工具注册表 |
| `app/services/planner.py` 直调 `openai` | `pi-ai` 统一 `ModelRegistry` | provider耦合，需抽象 |
| `plan_store` 内存+DB | `SessionManager` + `compaction` | 无压上下文，长trace会爆 |
| 技能写死在 `graph.py` | `Skills` 可热插 | 新增MCP需改代码 |

## 3. 转化清单 (落地)

| # | 转化 | 落地文件 | 验收 |
|---|------|----------|------|
| 1 | **工具注册表** | `app/agents/tools/registry.py` 4工具 `memory_search/rag_search/graph_search/write_tasks` | `planner` 仅通过注册表调用，可热插MCP |
| 2 | **统一LLM** | `app/core/llm.py` `UnifiedClient(provider=deepseek/qwen/anthropic)` 包装 `AsyncOpenAI` | `POST /plans?provider=qwen` 可切 |
| 3 | **会话压** | `app/agents/compaction.py` 超10轮自动摘要 | 长规划不超限 |
| 4 | **AGENTS.md** | `AGENTS.md` 项目级上下文，`pi` 式 `/reload` | 复用Pi规范 |

## 4. 最小落地 (本轮)

- 建 `app/agents/tools/registry.py` + `app/core/llm.py`，`planner` 改走注册表 + 统一LLM
- 补 `AGENTS.md` 根级上下文
- 保留原6节点行为，仅底层解耦，`pytest 35` 仍过

## 5. 后续

- 全量 Skills 化：`mcp.json` 转 `Skill` 热加载
- `pi-tui` 差异渲染参考，优化 `PlanStream` 大量事件
