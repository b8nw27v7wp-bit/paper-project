# TASK-BATCH — 问题修复清单
> 生成
> 已归档：2026-08-30 3项已闭环

请逐项完成以下修复，每修完一项跑一次 `cd apps/server && python -m pytest tests/ -v --tb=short` 确认不引入新问题。

---

## 任务1: 安装 pytest-asyncio 并修复 async 测试 ✅ 已完成

**问题**: `tests/test_agents_graph.py` 中 2 个 async 测试因缺 `pytest-asyncio` 失败
**修复**:
1. 在 `apps/server` 目录下创建 `pytest.ini` 或在现有配置中添加 asyncio mode
2. 确保 `requirements.txt` 中有 `pytest-asyncio`
3. 运行测试确认 35/35 全绿

---

## 任务2: 修复 Pydantic deprecation warning ✅ 已完成

**问题**: `apps/server/app/core/config.py` 使用了已废弃的 `class Config` 写法
**修复**:
```python
# 旧写法（删除）
class Config:
    env_file = ".env"
    env_file_encoding = "utf-8"
    extra = "ignore"

# 新写法（替换）
from pydantic_settings import ConfigDict

model_config = ConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)
```
同时确认 import 中有 `from pydantic_settings import ConfigDict`（已有的话不重复）

---

## 任务3: 修复 FastAPI regex 废弃警告 ✅ 已完成

**问题**: `apps/server/app/api/v1/stats.py` 中 `regex=` 参数已废弃
**修复**: 将所有 `regex=` 改为 `pattern=`
```
# 旧
Query(default="7d", regex="^(7d|30d)$")
# 新
Query(default="7d", pattern="^(7d|30d)$")
```
涉及 `get_overview`、`get_trend`、`run_experiment` 三个函数

---

## 完成后

1. 运行 `cd apps/server && python -m pytest tests/ -v --tb=short` 确认全绿
2. 运行 `cd apps/server && python -c "from app.main import app; print('import ok')"` 确认无 warning
3. 汇报结果

---

## 变更日志
- 2026-08-30 归档：3项已闭环（pytest-asyncio / ConfigDict / pattern），已验证 37 passed
