---
name: web_search
description: 网页搜索（真stdio优先，失败回退mock）
---

# 网页搜索 Skill

网页搜索（真stdio优先，失败回退mock）。调用 `web_search(query, top_k=3)`，经 `execute_tool` 生命周期（校验→before→执行→after→事件）。

示例：`web_search("间隔重复 遗忘曲线", 3)`
