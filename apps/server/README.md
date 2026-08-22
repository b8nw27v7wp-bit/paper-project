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
