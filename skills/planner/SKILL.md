---
name: planner
description: 智能学习规划，基于目标与记忆生成周计划
---

# Planner Skill

调用 `planner_generate(goal_id, preferences)` 生成任务，需先 `memory_search` 与 `graph_search`。

示例：`memory_search("拖延",5)` → `planner_generate(1, {hours_per_day:4})`
