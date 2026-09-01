# 开发规范与Git管理

> 版本：v0.2_20260826 | 完成度 P0-P3 92% (2026-08-26 增补)

## 1. 分支规范

- `main`: 可发布分支，受保护
- `dev`: 日常开发分支
- `feature/*`: 功能分支，如 `feature/memory-pgvector`
- `docs/*`: 文档分支

提交信息：`feat: 多Agent协作` `fix: 修复记忆召回` `docs: 更新架构` `chore: 升级依赖`

## 2. 目录规范（代码侧，与文档库分离）

```
apps/
 ├─ frontend/ (Vue3, 14视图 apps/frontend/src/views + router/index.ts:3, vite.config.ts:16 代理 /api→8000 ws:true)
 ├─ desktop/ (Electron 40, electron-builder externalBin/bin sidecar, better-sqlite3 WAL)
 ├─ server/ (FastAPI, 16组路由 app/api/v1/* 66端点, app/main.py:27 lifespan)
 └─ cli/ (Typer, apps/cli/main.py 4命令 trace/plan/graph/memory)
packages/ (预留)
```

> 2026-08-26 增补：修正过时路径 `app/frontend`/`apps/web` → `apps/frontend` (实际 `apps/frontend/src/views` 14文件), `app/server` → `apps/server/app/main.py`, 明确 `apps/server/app/api/v1` 下16组路由(原13→16, 新增 desktop/experiments/llm)与 `app/agents/tools/registry.py` 单一职责可热插。

## 3. 文档规范

- 统一Markdown，中文标题用 `##`，代码块标语言
- 每份文档头部含 `> 版本：v0.x_YYYYMMDD`
- 末尾含 `## 变更日志` 表
- 图表放 `02-需求与设计/diagrams/`，命名 `架构图-总览.drawio`

## 4. 环境规范

- Node >=22, pnpm >=9, Python 3.11, Rust stable(仅Tauri时需)
- 统一`.nvmrc` `pyproject.toml` `docker-compose.yml` (含 `ankane/pgvector:pg16` + `postgres/neo4j/redis/minio` 4服务, `app/core/database.py:26` WAL)
- 提交前 `pnpm lint` + `ruff check` + `npm run check` (`turbo.json:4` + `apps/frontend/package.json:11` `check: vue-tsc --noEmit && vite build`)
- 验证必过：`$env:PYTHONPATH=apps/server py -m pytest tests/ -q` 35/35 (26.26s) + `npm run build --prefix apps/frontend` 2987 modules 7.21s (2026-08-26)

> 2026-08-26 增补：补充 DB异步化 `app/core/database.py:26` `create_engine` + `create_async_engine(sqlite+aiosqlite)` + `PRAGMA journal_mode=WAL busy_timeout=5000`, 向量 `HNSW m=16 ef=64` `app/models/memory.py:17`, 检索 `asearch_memory` `app/services/memory.py:139` 真embedding, checkpoint `app/core/checkpoint.py:FileMemorySaver` 可恢复。

## 5. 版本与备份

- 文档变更先提 `docs/*` 分支，PR合并到`main`
- 每周打Tag `docs-v0.x`
- 重要PDF存 `05-附件/参考文献/`，不直接提交大文件到Git，用网盘+链接

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-22 | v0.1 | 初版规范 |
| 2026-08-26 | v0.2 | 增补：路径修正 apps/web→apps/frontend、接口13→16、视图12→14、完成度62%→92%、sidecar/WAL/HNSW/asearch、验证命令与 vite 7.21s 日志 |
