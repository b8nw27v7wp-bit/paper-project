---
name: calendar_create
description: 创建日历事件（真stdio优先，失败回退mock）
---

# 创建日历事件 Skill

创建日历事件（真stdio优先，失败回退mock）。调用 `calendar_create(title, start, end)`，经 `execute_tool` 生命周期（校验→before→执行→after→事件）。

示例：`calendar_create("英语晨读", "2026-09-10T09:00:00+00:00", "2026-09-10T10:00:00+00:00")`
