---
name: memory
description: 长期记忆检索与沉淀，pgvector Top5 注入规划
---

# Memory Skill

调用 `memory_search(query, top_k=5)` 检索个性化记忆，`create_memory(content)` 沉淀。

示例：`memory_search("拖延", 5)` → `[{content, score}]`
