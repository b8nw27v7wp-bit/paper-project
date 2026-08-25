# TASK-BATCH-P1D — Pi 对比分析 + 迁移落地

> 工作目录：E:\paper project
> Pi 代码在 E:\paper project\Pi\ 目录下
> 当前项目后端在 E:\paper project\apps\server\
> LLM：智谱 GLM-4.7 Flash（免费）

---

## 任务: 对比 Pi 与当前项目的架构差异，找出值得学习的优点，落地迁移

### 步骤1: 阅读 Pi 核心代码

请阅读以下 Pi 源码文件，理解其架构设计：

1. `Pi/packages/agent/src/agent.ts` — Agent 核心循环
2. `Pi/packages/agent/src/agent-loop.ts` — Agent loop 实现
3. `Pi/packages/agent/src/types.ts` — 类型定义
4. `Pi/packages/agent/src/harness/` — 工具注册和 harness
5. `Pi/packages/ai/src/providers/` — 多 provider 统一接口
6. `Pi/packages/ai/src/models.ts` — 模型管理
7. `Pi/packages/coding-agent/src/core/` — coding agent 核心

### 步骤2: 阅读当前项目核心代码

请阅读以下文件：

1. `apps/server/app/agents/graph.py` — LangGraph 多 Agent
2. `apps/server/app/agents/state.py` — Agent 状态
3. `apps/server/app/agents/tools/registry.py` — 工具注册表
4. `apps/server/app/core/llm.py` — 统一 LLM 客户端
5. `apps/server/app/services/planner.py` — 规划服务

### 步骤3: 输出对比分析报告

将分析结果写入 `00-管理/Pi对比分析报告.md`，包含：

1. **Pi 的核心优点**（列出 5-8 个具体的设计亮点）
2. **当前项目的不足**（对照 Pi 找差距）
3. **可迁移的改进点**（具体到代码层面）
4. **迁移优先级**（P0 必做 / P1 建议做 / P2 锦上添花）

### 步骤4: 落地迁移（选 P0 优先级的 2-3 项）

根据分析报告，选择最有价值的 2-3 项改进落地到代码中。例如可能包括：

- Agent loop 重试/错误恢复机制
- 工具调用的类型安全和验证
- 更好的状态管理和 checkpoint
- Provider fallback 链
- 测试 harness 改进

每项改动后跑测试确认不引入回归：
```bash
cd apps/server && python -m pytest tests/ -q
```

### 完成后验证

1. `python -m pytest tests/ -q` → 35/35 passed
2. `python -c "from app.main import app; print('ok')"` → ok
3. 汇报对比分析结论和迁移结果
