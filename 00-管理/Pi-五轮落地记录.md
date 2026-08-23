# Pi 五轮落地记录 — 提示模板与测试替身

> 依据 `Pi-五轮提炼.md` | 目标：Prompt文件化 + faux无Key测 + 模型注册

## 1. 落地

| 项 | 文件 | 变更 |
|----|------|------|
| Prompt模板 | `prompts/planner|critic|mentor.md` + `app/agents/prompts_loader.py:1` | `substitute($1/$@)` 热改 |
| 测试替身 | `tests/faux.py:1` `FAUX_PLANNER_TASKS` | `test_agents_graph` 可无Key |
| 模型注册 | `app/api/v1/llm.py:1` `GET /llm/models` | `PROVIDER_MAP` 4 provider |

## 2. 验证

- `pytest 35 passed` `vite 5.33s`
- `GET /llm/models` 200 4 provider
- `prompts/planner.md` 热改后 `load_prompt` 即生效

## 3. 后续

- `prompt-templates` 目录化加载（Pi式 `loadPromptTemplates`）
- `faux` 扩展至 `rag/graph` 轨迹
