# Pi 借鉴总账 — 轻量转化方案 + 二~五轮提炼与落地（合并版）

> 合并：2026-09-04（原 7 份 Pi 文档归一为本文件；《Pi对比分析报告.md》独立保留）
> 学习对象：`Pi` (earendil-works/pi, 4工具极简) | 目标：任务规划 Agent 更轻、可插拔、provider 无关
> 原文件：`Pi-轻量转化方案.md` `Pi-二轮提炼.md` `Pi-三轮精读报告.md` `Pi-三轮落地记录.md` `Pi-四轮整合报告.md` `Pi-五轮提炼.md` `Pi-五轮落地记录.md`

## 1. 一轮：轻量转化方案（2026-08-23）

| Pi 设计 | 要点 | 落点 |
|---------|------|------|
| 4工具极简 | `read/write/edit/bash` 单一职责，系统提示<1000 tokens | `agent/src/harness/tools/index.ts` |
| 统一LLM | `pi-ai` 20+ provider /login BYOK | `ai/src/*` `models.generated.ts` |
| 自扩展 | 运行时 Extensions/Skills/Templates TS自注册 | `agent/src/harness/skills.ts` |
| 会话 | `compaction/branch-summarization` 自动压上下文 | `harness/compaction/*` |
| 无内置权限 | 依赖容器化 (Gondolin/Docker/OpenShell) | `coding-agent/docs/containerization.md` |
| 质量 | `no any` `top-level import` `erasable TS` `npm run check` | `AGENTS.md` |

落地：`app/agents/tools/registry.py` 4工具注册表 + `app/core/llm.py` UnifiedClient + `app/agents/compaction.py` 会话压 + 根级 `AGENTS.md`。保留 6节点行为，仅底层解耦。

## 2. 二轮提炼 — 进阶轻量（agent-loop/compaction/skills/tui）

| 机制 | Pi 实现 | 要点 |
|------|---------|------|
| 双循环 | `runLoop` 外层 followUp + 内层 toolCalls/steering | 可边思考边接收用户插话 |
| 工具执行 | `sequential` vs `parallel`，`terminate` 标记 | 单工具强制串行，其余并行 |
| 截断保护 | `stopReason=="length"` 全量失败 | 防幻觉截断参数 |
| 上下文压 | `compaction` `branch-summarization` | 超限自动摘要 |
| 技能 | `harness/skills.ts` TS运行时热插 | 新增工具不改核心 |
| TUI | `tui` 差分渲染 | PlanStream 增量渲染 |

对表差距（转化去向）：steering 插槽（未做，见遗留）、memory/rag/graph 并行（已落地 researcher）、plan_store 压（`compaction.py` 阈值 20 已落地）、技能热插（`registry.py` 已具雏形）。

## 3. 三轮：精读 + 落地（技能目录化 + 熔断 + TUI差分）

精读要点：双循环+steering（`agent-loop.ts:796`）、工具并行+`terminate` 熔断、截断保护、`SKILL.md`+`loadSkills` 递归热插、TUI 差分（`Box/VStack/Text`）、compaction 阈值+分支摘要。

| 落地项 | 文件 | 变更 |
|--------|------|------|
| 技能目录化 | `skills/memory|rag|graph/SKILL.md` + `app/agents/tools/registry.py` | 启动扫 `skills/*/SKILL.md` 热插 |
| 熔断 | `app/agents/graph.py` `critic_node` 任务>30 熔断 + `should_replan` | 防截断死循环 |
| TUI差分 | `apps/frontend/src/components/PlanStream.vue` `max-h 320` + `slice(-20)` | 20+事件不卡 |
| 统一LLM | `app/core/llm.py` + `app/services/memory.py` | 已切 |

验证：pytest 35 passed、vite 5.35s（2026-08-23 基线）。后续：Skills 目录化扩展、faux provider 无Key测试。

## 4. 四轮整合报告 — 深度融入

| Pi 能力 | 本项目落地 | 文件 |
|---------|------------|------|
| 双循环+steering | `critic` 熔断 `terminate` | `app/agents/graph.py` |
| 技能目录化 | `skills/planner|memory|rag|graph/SKILL.md` | `registry.py` |
| TUI差分 | `PlanStream` `slice(-20)` 虚拟化 | `PlanStream.vue` |
| 统一LLM | `UnifiedClient` | `app/core/llm.py` `memory.py` |

验证：pytest 35 passed、vite 5.37s；`POST /plans` 6节点 8事件，`GET /stream` 差分。后续：branch-summarization、faux provider。

## 5. 五轮：提炼 + 落地（提示模板与测试替身）

| Pi 机制 | 细节 | 落地 |
|---------|------|------|
| Prompt模板 | `loadPromptTemplates` 扫 `*.md` + `substituteArgs($1/$@/ARGUMENTS)` | `prompts/planner|critic|mentor.md` + `app/agents/prompts_loader.py` 热改 |
| Faux Provider | `test/suite/harness.ts` 伪LLM 按预设轨迹回放 | `tests/faux.py` `FAUX_PLANNER_TASKS`，`test_agents_graph` 无Key可测 |
| ModelRegistry | 统一模型注册 | `app/api/v1/llm.py` `GET /llm/models` 4 provider |

验证：pytest 35 passed、vite 5.33s、`GET /llm/models` 200。后续：prompt-templates 目录化、faux 扩展至 rag/graph 轨迹。

## 6. 遗留未落地（合并自各轮"后续"，未闭环项已归并至 待优化与补全清单.md §7）

- Steering 队列：`POST /plans/{trace_id}/steer` 规划中插话（Pi `agent.ts:282-311`）
- branch-summarization 分支压（超长 plan_store）
- 真增量 SSE：token 切块 delta 替代 `sleep(0.08)` 伪流（Pi `faux.ts:338-434`）
- faux 扩展至 rag/graph 轨迹
- 成本与 Token 核算（`calculateCost` 分层计费）

## 变更记录

| 日期 | 动作 |
|------|------|
| 2026-08-23~08-26 | 原七份文档各轮产出（见上方各节） |
| 2026-09-04 | 七份合并为总账，原文件删除；《Pi对比分析报告.md》保留独立 |
