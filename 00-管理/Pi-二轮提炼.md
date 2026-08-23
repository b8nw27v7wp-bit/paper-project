# Pi 二轮提炼 — 进阶轻量

> 精读 `Pi/packages/agent/src/agent-loop.ts:1` + `compaction/*` + `skills/*` + `tui`

## 1. 核心机制

| 机制 | Pi 实现 | 要点 |
|------|---------|------|
| **双循环** | `runLoop` 外层 followUp + 内层 toolCalls/steering | 可边思考边接收用户插话，`hasMoreToolCalls` 驱动 |
| **工具执行** | `sequential` vs `parallel`，`terminate` 标记 | 单工具 `sequential` 强制串行，其余并行 |
| **截断保护** | `stopReason=="length"` 全量失败 | 防幻觉截断参数 |
| **上下文压** | `compaction` `branch-summarization` | 超限自动摘要，`shouldCompact` |
| **技能** | `harness/skills.ts` TS运行时热插 | 新增工具不改核心 |
| **TUI** | `tui` 差分渲染 | PlanStream 可借鉴增量渲染 |

## 2. 对表本项目

| 本项目 | 差距 | 转化 |
|--------|------|------|
| `graph.py` 6节点固定流 | 无内外双循环、无steering | 加 `getSteeringMessages` 插槽，支持规划中改需求 |
| `critic` 串行 | 无并行工具 | `memory/rag/graph` 可并行 |
| `plan_store` 无压 | 长trace会爆 | 加 `compaction` 10轮摘要 |
| 技能写死 | 无热插 | `registry.py` 已具雏形，补 `Skills` 加载 `mcp.json` |

## 3. 最小深化 (本轮已落地)

- `researcher` 已用 `registry.list_tools()` 演示热插
- `UnifiedClient` 已统一 `embed`/`chat`
- 下一步：`agent-loop` 式 `EventStream` 替换当前 `plan_store` 列表，转 `tool_execution_start/end` 细粒度
