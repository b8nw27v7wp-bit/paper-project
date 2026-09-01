# API接口设计

> 版本：v0.5_20260830 | 02-需求与设计 | 详细版 | 完成度94% (2026-08-30 增补 工作台SSE/Graph/Inspector) | 16组66端点(工作台复用Plan组) 视图15 F15-F17 M7

## 修订历史

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-22 | v0.3 | 补全每接口请求/响应/错误/限流全量 |
| 2026-08-26 | v0.4 | 增补：路由13→16组 66端点、视图12→14、完成度92%、sidecar/WAL/HNSW/asearch、验证 |
| 2026-08-30 | v0.5 | 工作台SSE细化与Graph/Inspector说明 |

## 1. 约定

- Base: `/api/v1`
- 认证: `Authorization: Bearer <JWT>`，Electron Main代理自动注入
- 格式: JSON, 时间ISO8601, 分页`page/size`, 统一`{code,msg,data}`
- 流式: `text/event-stream` SSE
- 校验: Pydantic严格，错误40001

## 2. 接口清单（2026-08-26 修正：原10组26接口→现16组66端点）

| 分组 | 数量 | 说明 | 代码 |
|------|------|------|------|
| Auth | 4 | 登录注册/me/verify | `auth.py:49` `/auth/register` `auth.py:60` `/auth/login` `auth.py:68` `/auth/me` `auth.py:73` `/auth/verify` |
| Goal | 5+5 | 目标CRUD + async variant | `goals.py:24` 5 + `goals_async.py:27` 5 |
| Plan | 3 | 规划+流式+日志(6节点8事件) | `plans.py:25` `plans.py:203` `plans.py:288` |
| Task | 5+5 | 任务CRUD+打卡+batch + async | `tasks.py:33` 5 + `tasks_async.py:41` 5 |
| RAG/Graph | 3+2 | 入库检索图谱 | `rag.py:16` `rag.py:76` `rag.py:94` + `graph.py:12` `graph.py:19` |
| Memory | 2 | 记忆检索 | `memory.py:17` `memory.py:28` |
| MCP | 3 | Server/tools/调用 | `mcp.py:15` `mcp.py:20` `mcp.py:25` |
| Multimodal | 3 | OCR/ASR/capabilities | `multimodal.py:8` `multimodal.py:28` `multimodal.py:47` |
| Reflection | 3 | 周报 latest/week/run | `reflection.py:13` `reflection.py:26` `reflection.py:34` |
| Stats | 3 | 统计 overview/trend/experiment | `stats.py:10` `stats.py:15` `stats.py:20` |
| Health | 2 | 健康探针 | `health.py:18` `/health` `health.py:85` `/health/detailed` + `main.py:107` `/health` root |
| LLM | 1 | 模型列表 | `llm.py:7` `/llm/models` |
| Desktop | 6 | 桌面 sidecar同步 | `desktop.py:37` `desktop.py:58` `desktop.py:76` `desktop.py:88` `desktop.py:94` `desktop.py:109` |
| Agent | 2 | SystemAgent 单点对外（Agent 2组） | `app/agents/system_agent.py:1` `GET /agent/manifest` `POST /plans` 即 SystemAgent.ainvoke |
| Experiments | 7 | 实验套件 | `experiments.py:26` `experiments.py:40` `experiments.py:53` `experiments.py:76` `experiments.py:98` `experiments.py:111` `experiments.py:123` |

> 2026-08-26 增补：原文档 13→16组逻辑 (新增 desktop/experiments/llm)，文件数 `app/api/v1/*.py` 17个(含 `goals_async/tasks_async` 各5)，`grep router.(get|post|put|delete)` 66端点；旧26接口为P0-P1子集，现全量已验 35/35。

## 3. 详细接口

### 3.1 Auth

**POST /auth/login**

- 请求: `{username:string(3-64), password:string(6-64)}`
- 响应200: `{token:string, user:{id,username,major}}`
- 错误40101: 密码错

**POST /auth/register**

- 请求: `{username, password, major?}`
- 响应201: `{user}`
- 错误40001: 重名

### 3.2 Goal

**POST /goals**

- 请求: `{title:string 1-200 必填, description?:string 0-2000, deadline:string ISO8601 必填 >now+1d, subject?:string}`
- 响应201: `Goal{id,title,deadline,status,created_at}`
- 错误40001: 标题空/截止非法

**GET /goals?status=active&page=1&size=20**

- 响应200: `{items:Goal[], total:int}`

**GET /goals/{id}**

- 响应200: `Goal + tasks:Task[]`

**PUT /goals/{id}**

- 请求: `{title?, deadline?, status?}`
- 响应200: `Goal`

**DELETE /goals/{id}**

- 响应204

### 3.3 Plan（核心）

**POST /plans** `SystemAgent 单点` — 即 `SystemAgent.ainvoke` 对外唯一入口

> SystemAgent 单点：`POST /plans` 即 `SystemAgent.ainvoke`，对外单一智能体，内部编排6子Agent，trace_id 贯穿。

- 请求: `{goal_id:int, preferences?:{hours_per_day:1-8, preferred_time:string}}`
- 响应200: `{trace_id:uuid, tasks:Task[], mentor_msg:string, citations:[]}`
- 错误50001: LLM超时

**GET /plans/stream?trace_id=uuid**

- 响应SSE: `Content-Type: text/event-stream`，8事件均带 `id:` 与 `retry: 3000`，支持 `Last-Event-ID` 断线续播（后端 `cache:workbench:{trace_id}` 5m 重放）

| # | event | data 示例 | 说明 |
|---|-------|-----------|------|
| 1 | `init` | `{"trace_id":"...","goal_id":1}` | 初始化 |
| 2 | `thought` | `{"agent":"planner","text":"检索记忆..."}` | Agent思考 |
| 3 | `tool_call` | `{"tool":"memory_search","args":{"q":"拖延"}}` | 工具调用 |
| 4 | `tool_result` | `{"tool":"memory_search","result":[...]}` | 工具结果 |
| 5 | `task_created` | `{"task":{"id":10,"title":"背单词","planned_start":"2026-08-25T09:00:00Z"}}` | 任务创建 |
| 6 | `critic` | `{"agent":"critic","suggestion":"..."}` | 评审意见 |
| 7 | `mentor` | `{"msg":"已为你规划3任务"}` | 导师总结 |
| 8 | `done` | `{"trace_id":"...","status":"completed"}` | 完成 |

- 帧格式示例:
```
id: 3
retry: 3000
event: tool_call
data: {"tool":"memory_search","args":{"q":"拖延"}}

```
- 断线: 客户端 `Last-Event-ID` 重连，后端从 `cache:workbench:{trace_id}` 按 `id` 续发

**GET /plans/{trace_id}/logs**

- 响应200: `agent_run_log[]`（按 `created_at, id` 升序，复用 `trace_id+agent_name` 联合索引）

**GET /plans/{trace_id}/graph** *(工作台复用Plan组，不新增路由组)*

- 响应200: `{nodes:[{id:"planner",name:"Planner",status:"done|running|pending",started_at,finished_at}], edges:[{from:"planner",to:"executor",type:"next"}], status:"running|completed|failed", trace_id}`
- 来源：优先 `cache:graph:{trace_id}` 5m，未命中则由 `agent_run_log` 聚合重建；前端 ECharts DAG 渲染，6节点可视化

**GET /plans/{trace_id}/inspector** *(工作台复用Plan组)*

- 响应200: `{state: object, logs: agent_run_log[], patch: {before, after}}`，复用 `GET /plans/{trace_id}/logs` + `state` 快照
- 用途：Inspector 右栏 JsonView 展示当前 `state`、子调用树 `logs[].tool_calls`、前后 `patch` 对比；前端 `workbench.ts` Pinia 聚合

### 3.4 Task

**GET /tasks?goal_id=1&status=todo&page=1&size=20**

- 响应200: `{items:Task[], total}`

**PUT /tasks/{id}**

- 请求: `{title?, planned_start?, planned_end?, priority? 1-5, status?}`
- 响应200: `Task`

**POST /tasks/{id}/complete**

- 请求: `{actual_duration:int 0-600, completion_rate:float 0-1, delay_reason?:string 0-500}`
- 响应200: `task_execution_log`

**POST /tasks/batch**

- 请求: `{tasks:[{title, planned_start, planned_end, priority}]}`
- 响应201: `Task[]`

**DELETE /tasks/{id}**

- 响应204

### 3.5 RAG/Graph

**POST /rag/ingest** (multipart)

- 请求: `file: PDF/JPG/PNG <20M, subject?:string`
- 响应200: `{chunks:32, knowledges:12}`

**GET /rag/search?q=链表&top_k=10&subject=数据结构**

- 响应200: `{chunks:[{content, score, citations:{page}}], graph:[{name, prereq}]}`

**GET /graph?subject=数据结构**

- 响应200: `{nodes:[{id,name}], edges:[{from,to,type:PREREQUISITE}]}`

### 3.6 Memory

**GET /memory/search?q=拖延&top_k=5**

- 响应200: `memory_chunk[]`

**POST /memory**

- 请求: `{content:string 1-1000, type:memory/knowledge}`
- 响应201: `memory_chunk`

### 3.7 MCP

**GET /mcp/servers**

- 响应200: `[{name, status:running/stopped}]`

**POST /mcp/call**

- 请求: `{server:string, tool:string, args:object}`
- 示例: `{"server":"calendar","tool":"create_event","args":{"title":"背单词","start":"2026-08-25T09:00:00Z","end":"2026-08-25T10:00:00Z"}}`
- 响应200: `{event_id, result}`
- 错误50002: MCP失败

### 3.8 Multimodal

**POST /multimodal/ocr** (multipart image <10M)

- 响应200: `{courses:[{course,time, confidence}], text}`

**POST /multimodal/asr** (multipart audio <5M)

- 响应200: `{text, confidence}`

### 3.9 Reflection

**GET /reflection/week?week=2026-W34**

- 响应200: `reflection_report`

**POST /reflection/run**

- 请求: `{user_id}`
- 响应200: `reflection_report`

### 3.10 Stats

**GET /stats/overview?range=7d**

- 响应200: `{completion_rate:0.82, delay_rate:0.15, avg_load:2.3}`

**GET /stats/trend?range=30d**

- 响应200: `{dates:[], rates:[], loads:[]}`

## 4. Electron IPC

通道`codex_desktop:message-from-view`，方法`plan:create, task:complete, memory:search, graph:getState, inspector:open, workbench:sync`，每handler含`origin`，zod校验，Main代理`fetch`自动加头。
- `graph:getState` → 代理 `GET /plans/{trace_id}/graph` 取 `{nodes,edges,status}`
- `inspector:open` → 代理 `GET /plans/{trace_id}/inspector` 取 `{state,logs,patch}`
- `workbench:sync` → 聚合 SSE 重放 `cache:workbench:{trace_id}` + graph/inspector，快照可选落 `better-sqlite3 workbench_state`

## 5. 错误码

| code | HTTP | 说明 |
|------|------|------|
| 40001 | 400 | 参数校验(Pydantic) |
| 40101 | 401 | 未认证 |
| 40301 | 403 | 无权限 |
| 40401 | 404 | 资源不存在 |
| 42901 | 429 | 限流(Redis) |
| 50001 | 500 | LLM超时 |
| 50002 | 500 | MCP失败 |
| 50003 | 500 | 向量库失败 |

## 6. 安全与限流

- JWT 7d, Redis session
- `rate:llm:{user_id}` 10/min, `rate:plan` 5/min
- contextIsolation, 严格校验

## 7. 示例

```bash
curl -H "Authorization: Bearer $TOKEN" -X POST /api/v1/plans -H "Content-Type: application/json" -d '{"goal_id":1}'
curl -N -H "Authorization: Bearer $TOKEN" /api/v1/plans/stream?trace_id=xxx
```

## 8. 2026-08-26 增补实测

- **视图数**：`apps/frontend/src/views` 14文件 (`Calendar/Dashboard/Experiments/Gantt/Goals/HealthCheck/Home/KnowledgeGraph/LargeScreen/MCP/RAG/Reflection/TaskBatch/Week`) 原12→14 新增 `ExperimentsView/LargeScreenView`
- **完成度**：P0 100% + P1 80% → 总体92% (Pi报告 2026-08-26)
- **验证**：`PYTHONPATH=apps/server py -m pytest tests/ -q` 35/35 26.26s + `vite build` 7.21s 2987 modules + `pgvector_bench 500` 108ms + `graph_bench 10k/50k` 107ms (2026-08-26)

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-22 | v0.3 | 每接口请求/响应/错误全量 |
| 2026-08-26 | v0.4 | 增补路由13→16(66端点)/视图12→14/完成度92%/sidecar/WAL/HNSW/asearch/验证 |
| 2026-08-30 | v0.5 | 工作台：SSE 8事件带id/retry、新增graph/inspector复用Plan组、IPC补3方法 |
