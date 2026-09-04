# P1 加深计划 — 四方向（ReAct/双校验/个性化/反思）

> 版本 v0.2_20260904 | 状态：✅已验收 | 前置 P1-W9-11简化版 | 目标：论文可写 ReAct+双校验+个性化+反思闭环
> 基线（2026-09-04）：pytest 40 passed 18.2s · vite 6.25s

## 1. 目标与验收

将简化4节点（规则Critic+模板Mentor）加深为**完整6节点可追溯**，支撑 02-06-UI/03-六大模块 论文图。

| 方向 | 现状 | 加深后 | 验收 | 状态 | 证据 |
|------|------|--------|------|------|------|
| ReAct工具链 | Planner直出 | Planner `thought→memory_search→graph_search→vector_search→generate` 逐工具落 `tool_calls` | SSE 4工具事件，`agent_run_log` 可查 | ✅ | plans.py:335-366 SSE 8类事件；plans.py:407-412 六节点 tool_calls 落 AgentRunLog |
| Critic双校验 | 规则2项 | 规则3项(重叠/超载/前置) + LLM JSON `{"pass":bool}` 二次校验 | 拦截率>20%，`critic_feedback` 含LLM | ✅ | graph.py:291-359：熔断(任务>30)+重叠>30%+单日>4h+前置缺失+LLM复核 |
| Mentor个性化 | 模板一句 | 读 `task_execution_log` 拖延史+记忆，生成20字激励 | 含拖延原因 | ✅ | graph.py:362-393 `_analyze_mem_delay` + 记忆Top2 + hours_per_day 差异化 |
| 扩展 | 4节点 | 加 `Researcher`(RAG专职) + `Reflector` 周patch回注，形成 6节点 | `graph` 6节点，`Reflector` 可手动触发 | ✅ | graph.py:494-499 add_node×6；patch 手动可查 |

## 2. 设计

- 节点编排：LangGraph `StateGraph` 6节点 `planner→researcher→executor→critic→mentor→reflector`（graph.py:494-505，支持 Pi 风格 checkpointer）；critic 条件边 `should_replan`（graph.py:481-488）：`terminate` 直达 mentor，`critic_feedback` 非空且 `rewrites<2` 回 planner 重写，否则进 mentor
- ReAct：plans.py SSE 8类事件 `thought/tool_call_start/tool_call/tool_call_end/task_created/critic_feedback/mentor_msg/reflector_patch/done`（plans.py:335-366）；tool_call_start/end 成对，满足子调用树可折叠；通过时也补发空 `critic_feedback` 保证 8 类齐全（plans.py:359）
- Researcher 并行：`_call_mem/_call_rag/_call_graph` 三检索 `asyncio.gather(..., return_exceptions=True)`（graph.py:246），Pi 并行启示落地
- Critic 双校验：规则3项（重叠>30%/单日>4h/前置缺失）+ 熔断（任务>30 直接 `terminate`，graph.py:291-295）+ LLM JSON 二次校验（graph.py:50-55，temperature=0.2）；`should_replan≤2轮` 防死循环
- Mentor：读 `task_execution_log` 拖延史（`_analyze_mem_delay`，拖延≥2次给原因提示）+ 记忆 Top2 + 偏好 hours_per_day + 图谱前置数 + 学科维度生成 `mentor_msg`
- Reflector：`patch{reduce_load/add_buffer/reallocate}` → `reflection_report.next_plan_patch` → POST /plans 按周（Wxx）合并回注 prefs（plans.py:219-260，`_merged_from_patch` 防重复注入）
- Prompts：根目录 `prompts/{planner,critic,mentor}.md`，frontmatter 格式（description/argument-hint），`prompts_loader.py` 统一加载；`app/agents/prompts.py` 直用

## 3. 已落地记录

- ✅ 6节点图重构：graph.py:494-505 `add_node`×6 + 条件回边；`agent.py:192-197` 六节点日志全落库
- ✅ ReAct SSE 8事件：plans.py:335-366；`agent_run_log` 可查 trace_id 贯穿
- ✅ Researcher 并行3检索：graph.py:246 `asyncio.gather`，检索不因串行叠加
- ✅ Critic 双校验+熔断：graph.py:291-359；规则3项 + LLM JSON + 任务>30 熔断 + 重写≤2轮
- ✅ Mentor 拖延史个性化：graph.py:362-393
- ✅ Reflector patch 回注：plans.py:123-143 patch 触发 replan 回边（`_build_graph_from_logs`，critic→planner type=replan 红虚线）
- ✅ 2026-09-04 新增：reflector patch 含重分配类键即高亮 replan 边，前端可追溯

## 4. 验证清单（实测）

- ✅ `pytest test_agents_graph` 5用例全过：test_critic_overlap / test_critic_daily_overload / test_critic_pass / test_graph_normal / test_graph_replan
- ✅ `pytest` 全量 40 passed 18.2s（含 test_plans.py:94 `test_reflector_patch_replan_edge` 正反两例）
- ✅ `vite build` 6.25s
- ✅ SSE 8事件序列齐全（含通过时补发空 critic_feedback）
- ✅ prompts 3文件 + skills 4个 SKILL.md（graph/memory/planner/rag）加载无报错

## 5. 后续衔接

- 前端 02-06 UI 不动，PlanStream 按 tool_call_start/end 折叠子调用树
- 文档：`02-需求与设计/03-六大模块详细设计.md` M1节按本页证据同步
- `00-管理/P1-W9-11` 升级为 v0.2 依据本页；下一轮 P2 候选：critic LLM 校验缓存、reflector patch 执行率统计

## 变更日志

- 2026-08-23 v0.2 初版：四方向目标表格（ReAct/双校验/个性化/反思）
- 2026-09-04 统一模板重写+匹配度核验：逐项标注 ✅ 落地证据（行号已复核），基线 pytest 40 passed 18.2s / vite 6.25s
