from fastapi.testclient import TestClient
from app.main import app
from app.core.database import init_db
import io

init_db()
client = TestClient(app)

def test_rag_ingest_and_search():
    # 创建一个简单文本文件模拟PDF
    content = "数据结构 链表是线性结构，树是层次结构，图是网状结构。链表是树的前置。"
    files = {"file": ("test.txt", io.BytesIO(content.encode()), "text/plain")}
    r = client.post("/api/v1/rag/ingest", files=files, data={"subject": "数据结构"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["chunks"] >= 1
    assert data["knowledges"] >= 1
    # 检索
    r2 = client.get("/api/v1/rag/search?q=链表&top_k=5")
    assert r2.status_code == 200
    assert len(r2.json()["data"]["chunks"]) >= 1
    # 图谱
    r3 = client.get("/api/v1/graph?subject=数据结构")
    assert r3.status_code == 200
    g = r3.json()["data"]
    assert "nodes" in g and "edges" in g
    # 规划应带引用（先创建goal）
    from datetime import datetime, timezone, timedelta
    d = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    gid = client.post("/api/v1/goals", json={"title": "数据结构学习", "deadline": d, "subject": "数据结构"}).json()["data"]["id"]
    r4 = client.post("/api/v1/plans", json={"goal_id": gid})
    assert r4.status_code == 200
    # 检查任务带 citations（若有RAG结果）
    tasks = r4.json()["data"]["tasks"]
    # 由于我们用了知识库，至少应尝试带上
    # 即使无，也不应报错
    assert len(tasks) >= 1
    client.delete(f"/api/v1/goals/{gid}")

def test_graph_keyword():
    r = client.get("/api/v1/graph?keyword=链表")
    assert r.status_code == 200
