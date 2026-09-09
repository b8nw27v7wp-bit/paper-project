---
name: todo_create
description: 创建待办事项（真stdio优先，失败回退mock）
---

# 创建待办 Skill

创建待办事项（真stdio优先，失败回退mock）。调用 `todo_create(title, priority=3)`，经 `execute_tool` 生命周期（校验→before→执行→after→事件）。

示例：`todo_create("完成数学习题", 2)`
