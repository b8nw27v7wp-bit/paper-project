# Pi 三轮精读报告 — 高阶轻量

> 精读 `agent-loop.ts:796` `tui/*` `skills.ts:386` `compaction/*`

## 1. 核心发现

| 机制 | 细节 | 启示 |
|------|------|------|
| **双循环+steering** | 外层 `followUpMessages` + 内层 `toolCalls/pendingMessages`，支持规划中插话 | 本项目 `critic` 重规划可接收用户实时改偏好 |
| **工具并行** | `sequential` 标记 + `terminate` 熔断，截断时全失败 | `memory/rag/graph` 已并行，可加 `terminate` 熔断 |
| **截断保护** | `stopReason=="length"` 时全工具失败重发 | 防止LLM幻觉截断执行 |
| **技能热插** | `SKILL.md` + `loadSkills` 递归+ignore，`formatSkillInvocation` | `mcp.json` 可升级为 `SKILL.md` 目录 |
| **TUI差分** | `tui` 147导出，`Box/VStack/Text` 差分渲染 | `PlanStream` 大量事件可差分而非全量重绘 |
| **压测** | `compaction` 阈值+摘要，`branch-summarization` | `plan_store>20` 已压，可加分支 |

## 2. 本轮转化

- `researcher` 已并行，待加 `terminate` 熔断
- `compaction.py` 已阈值20，下一步加 `branch` 压
- `registry.py` 已热插 `mcp.json`，下一步转 `SKILL.md` 目录
- `PlanStream.vue` 已支持8事件，下一步差分渲染

## 3. 下一步

- `Skills` 目录化：`skills/memory/SKILL.md` 等
- `TUI` 差分：`PlanStream` 虚拟列表
- `faux provider`：`test_agents_graph` 改用 `faux` 无需真实Key
