# 智能学习任务规划与管理的智能体 — Monorepo

> 题目：基于多智能体协作与记忆增强的自进化学习任务规划与管理的智能体 — 融合MCP工具链与多模态感知的知识驱动架构  
> 版本: v0.1 P0地基 | 文档库: `E:\paper project`

## 快速开始

### 1. 环境要求
- Node >=22, pnpm >=9 (`npm i -g pnpm@9` 或 `corepack enable`)
- Python 3.11+ (推荐 3.11，3.14 已兼容)
- Docker Desktop (PG16+pgvector, Neo4j5, Redis7, MinIO)
- Git

### 2. 一键启动 (需 Docker)

```bash
# 复制环境变量
copy .env.example .env

# 启动存储
docker compose up -d          # pg 5432, neo4j 7474/7687, redis 6379, minio 9000/9001

# 安装依赖
pnpm install

# 后端 (需另终端)
pnpm dev:server                # uvicorn 8000

# 前端
pnpm dev:web                  # vite 5173

# 桌面 (需前端已启动)
pnpm dev:electron             # electron 40
```

### 3. 健康检查

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/plans/stream?trace_id=test -N  # SSE 预留
```

前端: http://localhost:5173 含健康检查卡片

### 4. 目录

```
E:\code project\
├─ apps/frontend  # Vue3 + Vite + TS + Tailwind + Naive UI
├─ apps/desktop   # Electron 40 + preload + IPC
├─ apps/server    # FastAPI + SQLModel + pgvector/Neo4j/Redis
└─ docker-compose.yml
```

### 5. 常见问题

- `better-sqlite3` 编译失败: `pnpm rebuild` 或按文档预案降级 `electron-store`
- `uv` 未安装: 后端支持 `pip install -r requirements` 兜底
- Docker 未安装: 仅影响 PG/Neo4j/Redis，FastAPI/Web/Electron 仍可独立启动（健康检查显示 degraded）

## 文档

详见 `E:\paper project\ README.md` + `00-管理/P0-地基执行计划.md`

## 技术栈快照

SystemAgent: app/agents/system_agent.py:14 studying-planner | 标题“基于多智能体协作与记忆增强的自进化学习任务规划与管理的智能体”

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-30 | v0.4 | 同步新标题管理的智能体 + system_agent:14 |
| 2026-09-01 | v0.5 | 技术栈快照补 SystemAgent: app/agents/system_agent.py:14 studying-planner；抽检管理系统→管理的智能体 |
