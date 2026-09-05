# Agent-First 全站前端重构 — 20260905

> 版本 v1.0_20260905 | 形态基准：Codex/Qoder 式 agent 工作台 | 决策：全站重构 / 仅浅色 / 允许 markdown-it+highlight.js / 写库审批二期
> 前置：80cb41a（智能体短板修复）| 后端 SSE 8事件+Last-Event-ID 续传+6节点DAG+Inspector 已闭环

## 1. 目标形态

```
┌────┬──────────────┬──────────────────────────────┬───────────┐
│Rail│ 会话列表(真历史)│ Agent 转录流                   │ Inspector │
│图标 │ trace_id 聚合  │ 用户气泡 / thought(markdown流式) │ DAG折叠    │
│导航 │ 重放点击       │ 工具调用结构化折叠块(状态图标)     │ State/Logs│
│    │              │ task_created 卡片/critic徽标     │ /Patch    │
│    │              │ Composer(输入+single/multi+发送) │ (可折叠)   │
└────┴──────────────┴──────────────────────────────┴───────────┘
次级导航：目标/日历/图谱/RAG/反思/实验/MCP/健康/Dashboard(洞察卡可发起会话)
```

- 默认路由 `/agent`（HomeView 移除改 redirect）
- 全站 agent-first：Dashboard 数据卡改为可一键发起会话的洞察卡；其余功能视图收进 Rail 次级导航
- 主题维持苹果浅色系；design tokens 统一收敛（tailwind.config + style.css + App.vue 三处→一处）
- Electron：titlebar 拖拽区适配 Rail、菜单/快捷键对齐（⌘K 已有 CommandPalette）

## 2. 分波与文件域

| 波次 | Agent | 范围 | 主要文件 |
|---|---|---|---|
| W1-BE | A | 会话历史端点 | app/api/v1/plans.py、tests/test_plans.py |
| W1-FE | B | 依赖+tokens+shell骨架 | frontend package.json、tailwind.config、style.css、App.vue、router/、views/AgentWorkbenchView(新)、components/Markdown.vue(新)、views/HomeView(删) |
| W2-T | C | 转录流+composer+会话接线 | AgentWorkbenchView 内部、components/Transcript*(新)、api/plans.ts、stores/workbench.ts |
| W2-A | D | 全站 agent-first 收口 | Dashboard/LargeScreen 等视图改造、router meta |
| W2-EL | E | Electron 适配 | electron/main.ts、ipc/handlers.ts、preload.ts |
| W3 | 主控 | 回归+electron build+回写+提交 | — |

> W2 三 agent 文件域互不重叠（C 只动工作台链路，D 只动非工作台视图，E 只动 electron/）；依赖 W1 的 shell 骨架与后端端点。

## 3. 逐项改法与验收

（执行记录见 §7）

## 7. 执行记录（2026-09-05 填实）

| 项 | 状态 | 证据 |
|---|---|---|
| W1-BE | ✅ | plans.py:661-770 `GET /plans/sessions`（2查询聚合无N+1、user隔离fail-closed、mode/status/node_summary）；test_plans.py +4 用例 |
| W1-FE | ✅ | theme.ts 单一 tokens 来源；App.vue Rail 四分组图标导航；/agent 路由默认页+三栏骨架；HomeView 删；Markdown.vue（markdown-it 15.0.1 + highlight.js 11.12.0） |
| W2-T | ✅ | TranscriptView/ToolBlock/PlanCard/Notice 组件族；sessions store 接真数据；composer 双模式（createPlan mode 参数）；Inspector 四 Tab 可折叠+DAG节点→transcript定位；旧 WorkbenchView(510行)删除，/workbench→/agent（query 透传）；PlanStream 保留（GoalsView 仍用） |
| W2-A | ✅ | Dashboard agent 洞察台（横幅卡+一键发起会话，sessionStorage `agent:prefill` 契约）；NotFound/LargeScreen 回工作台入口；meta.group 对齐 Rail |
| W2-EL | ✅ | Agent 菜单三项（⌘N 新会话/⌘I 聚焦输入/⌘" 切换Inspector，⌘K 让位 CommandPalette）；preload onAgentCommand；nativeTheme 锁 light；win-unpacked 重建 23:29 |
| 主控收口 | ✅ | App.vue 移除 /workbench 预取与 keepAlive 引用、stub 物理删除；AgentWorkbenchView 消费 `agent:prefill`（预填 composer/goal）；redirect 闭包类型修正 |

**回归（主控复跑）**：pytest **93 passed** (298s) · `npm run check` 1 successful (vue-tsc+vite build) · lint:eslint 0 errors/2 warnings · electron dir build 成功

## 4. 新增依赖登记

| 依赖 | 位置 | 用途 | 状态 | 版本 |
|---|---|---|---|---|
| markdown-it | frontend deps | thought/mentor 消息 markdown 渲染 | 已装 | ^15.0.1 |
| highlight.js | frontend deps | 代码块高亮 | 已装 | ^11.12.0 |
| @types/markdown-it | frontend devDeps | 类型 | 已装 | ^14.2.0 |

## 5. 二期预留

- 写库审批：write_tasks 前 SSE `approval_required` 事件 + Composer 批准/拒绝（SSE 契约 +1 事件，后端 approval 网关）
- 暗色主题（tokens 收敛后成本极低）

## 6. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-09-05 | v1.0 | 首版：形态定稿+分波计划+依赖登记 |
| 2026-09-05 | v1.2 | 执行完成：W1(BE/FE)+W2(T/A/EL) 五子agent并行落地+主控收口（stub删除/预填接线）；§7 执行记录填实；回归 93 passed + check/eslint/electron build 全过 |
| 2026-09-05 | v1.1 | W1-FE 完成：依赖已装登记版本+tokens 收敛+Rail shell+/agent 骨架 |
