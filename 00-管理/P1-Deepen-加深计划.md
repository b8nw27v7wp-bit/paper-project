# P1 加深计划 — 四方向

> 版本 v0.2_20260823 | 前置 P1-W9-11简化版 | 目标：论文可写 ReAct+双校验+个性化+反思闭环

## 1. 目标

将简化4节点（规则Critic+模板Mentor）加深为**完整6节点可追溯**，支撑 02-06-UI/03-六大模块 论文图。

| 方向 | 现状 | 加深后 | 验收 |
|------|------|--------|------|
| ReAct工具链 | Planner直出 | Planner `thought→memory_search→graph_search→vector_search→generate` 逐工具落 `tool_calls` | SSE 4工具事件，`agent_run_log` 可查 |
| Critic双校验 | 规则2项 | 规则3项(重叠/超载/前置) + LLM JSON `{"pass":bool}` 二次校验 | 拦截率>20%，`critic_feedback` 含LLM |
| Mentor个性化 | 模板一句 | 读 `task_execution_log` 拖延史+记忆，生成20字激励 | 含拖延原因 |
| 扩展 | 4节点 | 加 `Researcher`(RAG专职) + `Reflector` 周patch回注，形成 6节点 | `graph` 6节点，`Reflector` 可手动触发 |

## 2. 落地

- `app/agents/graph.py` 重构为6节点 `planner→researcher→executor→critic→mentor→reflector` (reflector按需)
- `app/agents/prompts.py` 已加深，直接复用
- `app/services/memory|graph|rag` 已有，Planner内显式调用
- `app/api/v1/plans.py` 事件扩展 `research_*`
- 文档：`02-需求与设计/03-六大模块详细设计.md:1` M1节、`02-06 UI` 不动、`00-管理/P1-W9-11` 升级为 v0.2

## 3. 验证

- `pytest test_agents_graph` 增 `test_react_tools` `test_critic_dual`
- SSE 8事件序列
