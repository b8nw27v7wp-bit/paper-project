# Agent能力拓展设计 — 20260908

> 版本 v0.9_20260908 | 前置：`00-管理/04-Agent能力基线审查-20260908.md` | 约束：不改栈Vue3+FastAPI+LangGraph+pgvector，注册表单一职责，统一LLM，plan_store内存+DB，SSE契约只增不减

## P1 工具干活能力

输入：`preferences.require_calendar? + goal/tasks`；State增量：`task_persist.calendar_sync{enabled,tried,ok}`；流程：`executor write_tasks成功 → require_calendar==true时逐rows调calendar_create → _thought记录`；异常：MCP真stdio 3s超时失败回退mock，永不抛错；验收：`GET /agent/tools`可见三工具，`require_calendar`默认关。

## P2 自主规划执行

输入：`critic_feedback + rewrites`；State增量：`_patch{patch_id,auto_execute,retry_policy}`；流程：`should_replan rewrites<3`，第3轮仅`reorder/add_buffer`轻patch；`apply_patch_reallocation`遇重复`patch_id`直接返回深拷贝；审批批准后`_try_calendar_sync`（前3任务，失败跳过），拒绝/超时`_rollback_premature_tasks`；异常：重键剥离`reallocate/reduce_load/truncate`防移周抖动；验收：批准→落库+日历，拒绝无残留，`done.approved`齐全。

## P3 多Agent协作（7节点）

输入：`tasks+critic_feedback`；State增量：`_review{score,issues}`；流程：`critic→reviewer→mentor`，`critic通过→executor→reviewer→mentor`，`reviewer_node`纯函数`score=100-20*issues`；异常：旧6条trace缺reviewer则pending/running兼容；验收：`GET /plans/{trace}/graph` 7节点6边，`agent_run_log`7条，manifest `0.4.0+reviewer`。

## P4 记忆与自进化

输入：`memories + reflection_report.next_plan_patch`；State增量：`asearch(with_hints)->{results,hints{prefer_weekday,focus_subject,hours_bias}}`；流程：`extract_preference_hints`纯函数（显式键优先/星期众数/薄弱-科目正则/减负∓0.5），`normalize_patch_for_planner`泛化`reduce_*→reduce_load`+`add_buffer→buffer_minutes=15`；异常：`self_evolution`空/None回退before不伪增益，`estimated`标记不可引用；验收：`GET /stats/self-evolution + /experiments/self-evolution` 200，下周`prefs._merged_from_patch=true`。

## 变更日志

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-09-08 | v0.9 | 首版：P1-P4四节详细设计 |
