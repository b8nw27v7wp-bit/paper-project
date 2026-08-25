# Pi 对比分析报告

> 版本：v1.0_20260825 | 00-管理

## 一、Pi 的核心设计优点

### 1. 类型安全的工具系统（P0 必学）
Pi 的 `AgentTool<TParameters>` 使用 TypeBox schema 做参数校验，工具定义包含：
- `label`：UI 显示名
- `prepareArguments`：参数兼容性 shim（在 schema 校验前做转换）
- `execute`：执行函数，返回 `AgentToolResult<TDetails>`（含 content/details/usage/terminate）
- `executionMode`：per-tool 控制 sequential 或 parallel

**当前项目差距**：registry.py 的工具只是 `Callable` 没有 schema 校验，参数安全性差。

### 2. Before/After 工具钩子（P0 必学）
Pi 的 agent loop 提供：
- `beforeToolCall`：执行前可拦截（`{block: true, reason}`），用于权限控制
- `afterToolCall`：执行后可修改结果（替换 content/details/isError/usage）
- 两者都接收 `AbortSignal`，支持取消

**当前项目差距**：没有工具执行前后钩子，无法做权限控制或结果后处理。

### 3. 结构化事件系统（P1 建议学）
Pi 的 `AgentEvent` 是完整的类型化事件流：
- 生命周期：agent_start → turn_start → message_start → tool_execution_start → tool_execution_end → message_end → turn_end → agent_end
- 每个事件携带完整上下文（toolCallId, toolName, args, result, isError）

**当前项目差距**：SSE 事件是手写字符串（"thought"/"task_created"），没有统一事件类型。

### 4. 流式优先架构（P1 建议学）
Pi 的 `EventStream<AgentEvent, AgentMessage[]>` 是一等公民，所有操作都是流式的。`StreamFn` 接口强制"不能 throw，错误编码在流中"。

**当前项目差距**：planner.py 的 SSE 是事后拼接的，不是真正的流式。

### 5. 上下文管理（P1 建议学）
- `transformContext`：在 convertToLlm 前做上下文窗口管理（裁剪旧消息）
- `convertToLlm`：AgentMessage → LLM Message 的转换层
- `getSteeringMessages`：运行中注入引导消息
- `getFollowUpMessages`：轮次结束后注入后续消息

### 6. 优雅停止机制（P2 锦上添花）
`shouldStopAfterTurn` 允许在每轮结束后决定是否继续，避免无限循环。比当前的硬编码 `rewrites < 2` 更灵活。

### 7. 工具并行执行（P2 锦上添花）
`toolExecution: "parallel"` 允许同时执行多个工具，当前项目是纯串行。

---

## 二、可迁移的改进（P0 优先）

### 改进1: 工具类型安全 + schema 校验
给 registry.py 的工具加上参数 schema 和校验。

### 改进2: Before/After 工具钩子
在 agent loop 中加入工具执行前后钩子，支持权限控制和结果后处理。

### 改进3: 结构化 Agent 事件类型
定义统一的事件类型枚举，替换手写字符串。

---

## 三、当前项目的优势（Pi 没有的）

1. **LangGraph 多 Agent 协作**：Pi 是单 Agent loop，我们有 6 节点图 + 条件重规划
2. **RAG + 知识图谱**：Pi 没有内置 RAG/图谱，我们有完整管道
3. **记忆系统**：Pi 没有长期记忆，我们有 embedding + 沉淀 + 衰减
4. **自进化反思**：Pi 没有反思机制，我们有周反思 + plan_patch
5. **MCP 工具链**：Pi 的工具是硬编码的，我们支持热插拔 MCP server
