# AGENTS — 学习规划项目上下文 (Pi 风格)

- 运行 `pnpm install --ignore-scripts` / `npm run check` 前置
- 回答先于编辑，技术直述，无emoji
- 修改前全量读文件，`npm run check` 全过再 commit
- 新增依赖需在 `00-管理` 说明，不改栈 (`Vue3+FastAPI+LangGraph+pgvector`)
- 4工具注册表 `app/agents/tools/registry.py` 单一职责，可热插 `memory/rag/graph/write`
- 统一LLM `app/core/llm.py` provider无关 (deepseek/qwen/openai)
- `plan_store` 内存 + DB回退，`POST /plans?mode=multi` 6节点可追溯
- 前端 `http://localhost:5173` 代理 `/api`→8000，`vite build` 必过
