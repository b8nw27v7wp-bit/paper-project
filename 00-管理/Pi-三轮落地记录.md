# Pi 三轮落地记录 — 技能目录化 + 熔断 + TUI差分

> 版本 v0.1_20260823 | 依据 `Pi-三轮精读报告.md`

## 1. 落地

| 项 | 文件 | 变更 |
|----|------|------|
| 技能目录化 | `skills/memory|rag|graph/SKILL.md` + `app/agents/tools/registry.py:1` | 启动扫 `skills/*/SKILL.md` 热插 |
| 熔断 | `app/agents/graph.py:1` `critic_node` 任务>30 熔断 + `should_replan` | 防截断死循环 |
| TUI差分 | `apps/frontend/src/components/PlanStream.vue:1` `max-h 320` + `slice(-20)` | 20+事件不卡 |
| 统一LLM | `app/core/llm.py:1` + `app/services/memory.py:1` | 已切 |

## 2. 验证

- `pytest 35 passed` `vite build` 5.35s
- `plan_store` 20条压摘要 `compaction.py:1`

## 3. 审查

- `ruff` 17剩余非阻断，`vue-tsc 0`
- 逻辑：6节点ReAct+双校验+个性化+反思 完整，`35 tests` 全绿

## 变更

| 日期 | 动作 |
|------|------|
| 2026-08-23 | 三轮落地，技能+熔断+TUI |
