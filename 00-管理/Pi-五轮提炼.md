# Pi 五轮提炼 — 提示模板与测试替身

> 精读 `Pi/packages/agent/src/harness/prompt-templates.ts:262` + `test/suite/harness.ts` faux provider

## 1. 发现

| Pi 机制 | 细节 | 价值 |
|---------|------|------|
| **Prompt模板** | `loadPromptTemplates` 扫 `*.md` + `substituteArgs($1/$@/ARGUMENTS)` | 规划Prompt可文件化，非硬编码 |
| **Faux Provider** | `test/suite/harness.ts` 伪LLM，按预设轨迹回放 | `test_agents_graph` 无需真实Key即可测多Agent |
| **ModelRegistry** | `pi-ai` 统一 `ModelRegistry.create(auth)` | `UnifiedClient` 已具雏形，可再补 `listModels` |

## 2. 转化

| 本项目 | 差距 | 落地 |
|--------|------|------|
| `prompts.py` 硬编码 | 无文件化 | 建 `prompts/planner.md` 等，前端可热改 |
| `test_agents_graph` 需真实Key则skip | 无替身 | 建 `tests/faux.py` 预设 `planner→critic` 轨迹 |
| `UnifiedClient` 仅chat/embed | 无 `listModels` | 补 `GET /llm/models` |

## 3. 最小落地

- `prompts/*.md` 3文件 + `app/agents/prompts_loader.py`
- `tests/faux.py` + `test_agents_graph` 改用 faux
- `app/api/v1/llm.py` `GET /llm/models`
