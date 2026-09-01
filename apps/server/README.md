# Server - FastAPI

## 启动

```bash
# 方式1: uv (推荐)
uv sync
uv run uvicorn app.main:app --reload --port 8000

# 方式2: pip (兜底，无 uv 时)
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

健康检查: http://localhost:8000/health  http://localhost:8000/api/v1/health  http://localhost:8000/docs

## 向量检索模式切换 `USE_PG` (pgvector 真索引)

> 代码：`app/models/memory.py:17` 条件 `Vector(1536)`，`app/core/database.py:12,39-53,126-136` 自动建扩展与 HNSW，`alembic/versions/002_vector_idx.py:40-42` 幂等 `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`

- **默认 `USE_PG=0`（SQLite 降级，零依赖可跑）**：
  - `embedding` 存 `TEXT(JSON)`，`app/services/memory.py:73` 自动 `json.dumps(vec)`，检索走 `app/services/memory.py:82-125` 内存 `cosine()` + 30天衰减 `score*=0.7`
  - 适用：本地无 Docker、CI、演示
- **生产 `USE_PG=1`（Postgres+pgvector 真 HNSW）**：
  ```bash
  # 1. 启动 pgvector 镜像（docker-compose 已配 pgvector/pg16）
  docker compose up -d postgres
  # 2. 设环境变量并建库/扩展
  set USE_PG=1                  # Windows PowerShell: $env:USE_PG="1"
  export USE_PG=1              # Linux/Mac
  # DATABASE_URL 需指向 postgres（默认已是 postgresql://postgres:postgres@localhost:5432/app）
  alembic upgrade head          # 002 会建 idx_memory_embedding_hnsw + idx_memory_user_type
  # 或直接启动时自动建：init_db() 会 CREATE EXTENSION vector + CREATE INDEX IF NOT EXISTS
  py -m uvicorn app.main:app --port 8000
  ```
  - 生效判定：日志 `engine=postgresql://...` 且 `scripts/pgvector_bench.py` 输出 `USE_PG=True _USE_PG_VECTOR=True`
  - 切换无需改代码，重启即生效；同时兼容 `alembic downgrade/upgrade` 幂等

**压测验证**（`scripts/pgvector_bench.py:36-107`）：
```bash
py scripts/pgvector_bench.py --n 500 --q 20   # 已验 p95 106ms <200ms PASS (SQLite 500 行)
py scripts/pgvector_bench.py --n 5000 --q 100 # 目标 p95 <200ms (需 USE_PG=1 HNSW)
# PG 真索引时库内 `embedding <=> :vec` 走 HNSW，SQLite 时为 python 余弦批量评分对比
```

## 图谱 Neo4j + SQLite 双写

> 代码：`app/graph/neo.py:113-148` UNWIND 1k 批 + 索引 `CREATE INDEX ... FOR (n:Knowledge) ON (n.name)`，`app/graph/sqlite_graph.py:62-64` 三索引 `idx_nodes_subject/idx_edges_from/idx_edges_to`，`scripts/graph_bench.py:12-63`

- 写入链：`neo.py:add_triples()` → 内存 `_mem` → SQLite `sqlite_upsert_node/add_edge` → Neo4j `UNWIND $nodes/$edges MERGE`
- 读链：`neo.py:get_graph():152-210` **Neo4j → SQLite → 内存** 三级 fallback，`get_graph` 末段 `194-209` 合并去重（`existing_ids`/`existing_edges` 去重）
- `search_prereqs` BFS 2层：优先 `sqlite_search_prereqs`，回退 `neo.py:213-284` 双向 BFS

**压测**：
```bash
py scripts/graph_bench.py --nodes 1000 --edges 5000 --q 20   # 已验 p50 9ms p95 10.9ms
py scripts/graph_bench.py --nodes 5000 --edges 25000 --q 20  # 已验 p95 54ms
py scripts/graph_bench.py --nodes 10000 --edges 50000 --q 50 # 目标 p95 <500ms，已验 p95 ~107ms PASS
```

## 调度 周反思双 Job

> 代码：`app/scheduler/reflector.py:269-276` `register_reflector_jobs` 注册 `sun23:00 + mon09:00`，`app/scheduler/reflector.py:244-266` `weekly_reflection_job` 写 `_notify_log`，`app/main.py:32-62` lifespan 注入

- `weekly_reflection_job(user_id=1)`：`get_weekly_summary` 统计7天 `completion_rate/delay_rate/avg_load` → `generate_reflection` → `_notify_log.append({title:"周反思已生成", body, tag: week})` 供 `GET /api/v1/desktop/notifications` 拉取
- 注册：`main.py:lifespan` 内 `AsyncIOScheduler() + register_reflector_jobs(scheduler) + scheduler.start()`，异常回退单 `sun23:00`
- 验证：`py -m pytest tests/test_p2.py::test_reflection -v` 触发 `POST /reflection/run` 含 `completion_rate` + `week`

## MCP 工具链 + 真实 stdio 占位

> 代码：`app/mcp/client.py:42-65` 3 servers(mock) + `app/mcp/client.py:335-366` 3次指数退避 `0.1*2^attempt`，`mcp.json:2-6` 配置，`app/api/v1/mcp.py:15-30` 3接口

**当前 mock（零依赖可演示）**：
- `calendar.create_event / list_events`、`todo.create_todo / complete_todo`、`search.web_search` 均在 `app/mcp/client.py:70-150` 有完整 mock handler + 别名兼容，`call_tool` 超时5s重试3次并 `AgentRunLog` 记录

**真实 stdio 占位（待接 MCP SDK）**：
```jsonc
// mcp.json 真实示例（占位，待 npx 安装对应 server）
{
  "servers": {
    "calendar": { "command": "npx", "args": ["-y", "calendar-mcp"], "tools": ["create_event","list_events"] },
    "todo":     { "command": "npx", "args": ["-y", "todo-mcp"], "tools": ["create_todo","complete_todo"] },
    "search":   { "command": "npx", "args": ["-y", "search-mcp"], "tools": ["web_search"] }
    // 未来可加：{"command": "python", "args": ["-m", "mcp_server_calendar"]}
  }
}
```
- 框架已预留 `app/mcp/client.py:271-279` `command != "mock"` 时 `status` 探测分支，真实接入仅需：① 将 `mcp.json` 的 `command` 由 `mock` 改为 `npx`/`python`，② 在 `app/mcp/client.py:_call_once()` 的 `handler is None` 分支后插入 `mcp-sdk stdio` 调用（如 `mcp.ClientSession(command, args).call_tool`），保留现有超时/重试/日志不变
- 文档位置：`mcp.json` 顶部注释 + 本节；切换后 `GET /api/v1/mcp/servers` 将返回真实 `status: running`，`POST /api/v1/mcp/call` 透传真实结果

验证：`py -m pytest tests/test_p2.py::test_mcp -v` + `curl GET /api/v1/mcp/servers` `GET /api/v1/mcp/tools`

## 2026-08-26 增补 — 对表核验

- **路径/数量**：`apps/web`→`apps/frontend` (`apps/frontend/src/views` 14视图 + `router/index.ts:3`), `app/*`→`apps/*`, 路由 `13→16组` (新增 `desktop/experiments/llm` 3组, 含 `goals_async/tasks_async` 17文件 66端点 `app/api/v1`), 视图 `12→14`, 完成度 `62%→92%`
- **新增落地**：sidecar `apps/desktop externalBin/bin` + `app/core/database.py:26` WAL(`journal_mode=WAL busy_timeout=5000 async_engine aiosqlite`) + `app/models/memory.py:17` HNSW(`Vector(1536) m=16 ef=64`) + `app/services/memory.py:139` `asearch_memory` 真embedding
- **验证命令与日志**：
```bash
$env:PYTHONPATH="E:/paper project/apps/server"; py -m pytest tests/ -q  # 35 passed, 1 warning in 26.26s (2026-08-26)
npm run build --prefix apps/frontend  # vite v6.4.3 2987 modules in 7.21s (2026-08-26)
py scripts/pgvector_bench.py --n 500 --q 20  # p95 108ms PASS
py scripts/graph_bench.py --nodes 10000 --edges 50000 --q 50  # p95 107ms PASS
```
