# 开发规范与Git管理

> 版本：v0.1_20260822

## 1. 分支规范

- `main`: 可发布分支，受保护
- `dev`: 日常开发分支
- `feature/*`: 功能分支，如 `feature/memory-pgvector`
- `docs/*`: 文档分支

提交信息：`feat: 多Agent协作` `fix: 修复记忆召回` `docs: 更新架构` `chore: 升级依赖`

## 2. 目录规范（代码侧，与文档库分离）

```
app/
 ├─ frontend/ (Vue3)
 ├─ desktop/ (Electron)
 ├─ server/ (FastAPI)
 └─ cli/ (Typer)
```

## 3. 文档规范

- 统一Markdown，中文标题用 `##`，代码块标语言
- 每份文档头部含 `> 版本：v0.x_YYYYMMDD`
- 末尾含 `## 变更日志` 表
- 图表放 `02-需求与设计/diagrams/`，命名 `架构图-总览.drawio`

## 4. 环境规范

- Node >=22, pnpm >=9, Python 3.11, Rust stable(仅Tauri时需)
- 统一`.nvmrc` `pyproject.toml` `docker-compose.yml`
- 提交前 `pnpm lint` + `ruff check`

## 5. 版本与备份

- 文档变更先提 `docs/*` 分支，PR合并到`main`
- 每周打Tag `docs-v0.x`
- 重要PDF存 `05-附件/参考文献/`，不直接提交大文件到Git，用网盘+链接

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-22 | v0.1 | 初版规范 |
