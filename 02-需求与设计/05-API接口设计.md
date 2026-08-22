# API接口设计

> 版本：v0.3_20260822 | 02-需求与设计 | 详细版

## 修订历史

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-22 | v0.3 | 补全每接口请求/响应/错误/限流全量 |

## 1. 约定

- Base: `/api/v1`
- 认证: `Authorization: Bearer <JWT>`，Electron Main代理自动注入
- 格式: JSON, 时间ISO8601, 分页`page/size`, 统一`{code,msg,data}`
- 流式: `text/event-stream` SSE
- 校验: Pydantic严格，错误40001

## 2. 接口清单

| 分组 | 数量 | 说明 |
|------|------|------|
| Auth | 2 | 登录注册 |
| Goal | 5 | 目标CRUD |
| Plan | 3 | 规划+流式+日志 |
| Task | 5 | 任务CRUD+打卡 |
| RAG/Graph | 3 | 入库检索图谱 |
| Memory | 2 | 记忆检索 |
| MCP | 2 | Server与调用 |
| Multimodal | 2 | OCR/ASR |
| Reflection | 2 | 周报 |
| Stats | 2 | 统计 |

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

**POST /plans**

- 请求: `{goal_id:int, preferences?:{hours_per_day:1-8, preferred_time:string}}`
- 响应200: `{trace_id:uuid, tasks:Task[], mentor_msg:string, citations:[]}`
- 错误50001: LLM超时

**GET /plans/stream?trace_id=uuid**

- 响应SSE:
```
event: thought
data: {"agent":"planner","text":"检索记忆..."}
event: tool_call
data: {"tool":"memory_search","args":{"q":"拖延"}}
event: task_created
data: {"task":{"id":10,"title":"背单词","planned_start":"2026-08-25T09:00:00Z"}}
event: done
data: {"trace_id":"..."}
```
- 断线: `Last-Event-ID`重连

**GET /plans/{trace_id}/logs**

- 响应200: `agent_run_log[]`

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

通道`codex_desktop:message-from-view`，方法`plan:create, task:complete, memory:search...`，每handler含`origin`，zod校验，Main代理`fetch`自动加头。

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

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-22 | v0.3 | 每接口请求/响应/错误全量 |
