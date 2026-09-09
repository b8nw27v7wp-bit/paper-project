import time
import uuid
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import init_db

init_db()
client = TestClient(app)


def future(days=5):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _mk_goal(title="P2BE"):
    r = client.post("/api/v1/goals", json={"title": title + "-" + uuid.uuid4().hex[:6], "deadline": future(5)})
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def test_p2_ttl_constants_and_planstore_evict():
    from app.api.v1 import plans as plans_mod
    from app.services import planner as planner_mod
    from app.core import cache as cache_mod
    assert getattr(plans_mod, "PLAN_EVENTS_TTL", None) == 3600
    assert getattr(plans_mod, "WORKBENCH_TTL", None) == 300
    assert getattr(plans_mod, "PLAN_STORE_TTL", None) == 3600
    assert getattr(planner_mod, "PLAN_STORE_TTL", None) == 3600
    assert getattr(cache_mod, "_TTL", None) == 300
    # PlanStore 惰性淘汰：put 后改 exp 为过去，in/get 视为不存在
    ps = planner_mod.plan_store
    tid = "p2ttl" + uuid.uuid4().hex[:20]
    ps[tid] = [{"event": "done", "data": {}}]
    assert tid in ps
    try:
        ps._exp_map()[tid] = time.time() - 1
    except Exception:
        pass
    assert (tid in ps) is False
    assert ps.get(tid) is None
    # 未过期不误删
    tid2 = "p2ttl2" + uuid.uuid4().hex[:20]
    ps[tid2] = [{"event": "done", "data": {}}]
    assert tid2 in ps
    assert ps.get(tid2) is not None
    try:
        ps.pop(tid2, None)
        ps.pop(tid, None)
    except Exception:
        pass


def test_p2_pending_cap_200():
    from app.api.v1 import plans as plans_mod
    saved = dict(plans_mod._APPROVALS)
    try:
        plans_mod._APPROVALS.clear()
        now = time.time()
        for i in range(250):
            tid = f"p2pend{i:04d}{uuid.uuid4().hex[:8]}"
            plans_mod._APPROVALS[tid] = {
                "token": "t",
                "tasks_raw": [{"title": "x"}],
                "exp": now + 300,
                "approved": None,
                "user_id": 1,
                "created_at": now,
            }
        # 无 Redis 时走内存不变：mock _get_redis 返回 None 强制内存路径
        orig = plans_mod._get_redis
        plans_mod._get_redis = lambda: None
        try:
            r = client.get("/api/v1/plans/pending-approvals")
        finally:
            plans_mod._get_redis = orig
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert len(data["items"]) <= 200, len(data["items"])
        assert data["total"] <= 200
    finally:
        plans_mod._APPROVALS.clear()
        plans_mod._APPROVALS.update(saved)


def test_p2_pending_scan_iter_used(monkeypatch):
    from app.api.v1 import plans as plans_mod
    saved = dict(plans_mod._APPROVALS)
    try:
        plans_mod._APPROVALS.clear()
        now = time.time()
        seen = {"scan": False}

        class _FakeR:
            def scan_iter(self, match=None, count=None):
                seen["scan"] = True
                assert match == "plan:approval:*"
                for i in range(3):
                    yield f"plan:approval:scantid{i}"
            def get(self, k):
                import json as _j
                return _j.dumps({"token": "t", "tasks_raw": [], "exp": now + 300, "approved": None, "user_id": 1})
        monkeypatch.setattr(plans_mod, "_get_redis", lambda: _FakeR())
        r = client.get("/api/v1/plans/pending-approvals")
        assert r.status_code == 200, r.text
        assert seen["scan"] is True
        assert len(r.json()["data"]["items"]) == 3
    finally:
        plans_mod._APPROVALS.clear()
        plans_mod._APPROVALS.update(saved)


def test_p2_logs_inspector_limit():
    gid = _mk_goal("P2LogsLim")
    r2 = client.post("/api/v1/plans", json={"goal_id": gid, "preferences": {"hours_per_day": 2}})
    assert r2.status_code == 200, r2.text
    trace = r2.json()["data"]["trace_id"]
    try:
        r_all = client.get(f"/api/v1/plans/{trace}/logs")
        assert r_all.status_code == 200, r_all.text
        n = len(r_all.json()["data"])
        assert n >= 2, n
        r1 = client.get(f"/api/v1/plans/{trace}/logs", params={"limit": 1})
        assert r1.status_code == 200, r1.text
        assert len(r1.json()["data"]) == 1
        # 排序语义：截断为前 N 条（首条与全量首条一致）
        assert r1.json()["data"][0]["id"] == r_all.json()["data"][0]["id"]
        r_ins = client.get(f"/api/v1/plans/{trace}/inspector", params={"limit": 1})
        assert r_ins.status_code == 200, r_ins.text
        assert len(r_ins.json()["data"]["logs"]) == 1
        # 非法 limit 走 40001（validation handler）
        r_bad = client.get(f"/api/v1/plans/{trace}/logs", params={"limit": 0})
        assert r_bad.status_code == 400, r_bad.text
    finally:
        try:
            client.delete(f"/api/v1/plans/sessions/{trace}")
        except Exception:
            pass
        try:
            client.delete(f"/api/v1/goals/{gid}")
        except Exception:
            pass


def test_p2_calendar_agg_and_bad_month():
    gid = _mk_goal("P2CalAgg")
    # 固定远月隔离其他测试任务
    s1 = "2026-12-10T09:00:00+00:00"
    e1 = "2026-12-10T10:00:00+00:00"
    s2 = "2026-12-10T11:00:00+00:00"
    e2 = "2026-12-10T12:00:00+00:00"
    s3 = "2026-12-11T09:00:00+00:00"
    e3 = "2026-12-11T10:00:00+00:00"
    rb = client.post("/api/v1/tasks/batch", json={"tasks": [
        {"goal_id": gid, "title": "CalA", "planned_start": s1, "planned_end": e1},
        {"goal_id": gid, "title": "CalB", "planned_start": s2, "planned_end": e2},
        {"goal_id": gid, "title": "CalC", "planned_start": s3, "planned_end": e3},
    ]})
    assert rb.status_code == 201, rb.text
    ids = [x["id"] for x in rb.json()["data"]]
    # 其中一个 done
    rc = client.post(f"/api/v1/tasks/{ids[0]}/complete", json={"actual_duration": 60, "completion_rate": 1.0})
    assert rc.status_code == 200, rc.text
    try:
        r = client.get("/api/v1/tasks/calendar", params={"month": "2026-12"})
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["month"] == "2026-12"
        assert d["total"] >= 3
        assert "2026-12-10" in d["days"]
        assert d["days"]["2026-12-10"]["total"] >= 2
        assert d["days"]["2026-12-10"]["done"] >= 1
        assert set(ids[:2]) <= set(d["days"]["2026-12-10"]["tasks"])
        assert d["days"]["2026-12-11"]["total"] >= 1
        # 非法 month → 40001
        for bad in ["2026-13", "bad", "2026/12", ""]:
            rb2 = client.get("/api/v1/tasks/calendar", params={"month": bad})
            assert rb2.status_code == 400, f"{bad} {rb2.text}"
            assert rb2.json().get("code") == 40001
        # 他用户隔离：X-User-Id 9999 应看不到本用户任务
        r_other = client.get("/api/v1/tasks/calendar", params={"month": "2026-12"}, headers={"X-User-Id": "9999"})
        assert r_other.status_code == 200, r_other.text
        assert r_other.json()["data"]["total"] == 0
    finally:
        try:
            client.delete(f"/api/v1/goals/{gid}")
        except Exception:
            pass


def test_p2_batch_archive_halfsuccess_and_cap():
    g1 = _mk_goal("P2Arch1")
    g2 = _mk_goal("P2Arch2")
    try:
        r = client.post("/api/v1/goals/batch-archive", json={"ids": [g1, g2, 999999999]})
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert set(d["archived"]) == {g1, g2}, d
        assert d["missing"] == [999999999], d
        r1 = client.get(f"/api/v1/goals/{g1}")
        assert r1.json()["data"]["status"] == "archived"
        # 上限 50
        r_big = client.post("/api/v1/goals/batch-archive", json={"ids": list(range(1, 52))})
        assert r_big.status_code == 400, r_big.text
        assert r_big.json().get("code") == 40001
    finally:
        for g in (g1, g2):
            try:
                client.delete(f"/api/v1/goals/{g}")
            except Exception:
                pass


def test_p2_reflection_apply_idempotent():
    from sqlmodel import Session
    from app.core.database import engine
    from app.models.reflection import ReflectionReport
    week = "P2W-" + uuid.uuid4().hex[:6]
    with Session(engine) as s:
        rep = ReflectionReport(user_id=1, week=week, completion_rate=0.5, delay_rate=0.1, avg_load=1.0, analysis="a", next_plan_patch={"foo": 1})
        s.add(rep)
        s.commit()
    try:
        r1 = client.post(f"/api/v1/reflection/{week}/apply")
        assert r1.status_code == 200, r1.text
        d1 = r1.json()["data"]
        assert d1["week"] == week and d1["applied"] is True and d1["patch"] == {"foo": 1}
        r2 = client.post(f"/api/v1/reflection/{week}/apply")
        assert r2.status_code == 200, r2.text
        assert r2.json()["data"] == d1
        # global_state 落盘（契约键）
        with Session(engine) as s2:
            from sqlalchemy import text
            row = s2.execute(text("SELECT value FROM global_state WHERE key=:k"), {"k": f"reflection:applied:{week}"}).first()
            assert row is not None, "global_state reflection:applied:{week} 缺失"
        # 不存在周报 40401
        r404 = client.post("/api/v1/reflection/NOWEEK-404XYZ/apply")
        assert r404.status_code == 404, r404.text
        assert r404.json().get("code") == 40401
    finally:
        with Session(engine) as s3:
            from sqlalchemy import text
            try:
                objs = s3.exec(__import__("sqlmodel").select(ReflectionReport).where(ReflectionReport.week == week)).all()
                for o in objs:
                    s3.delete(o)
                s3.execute(text("DELETE FROM global_state WHERE key=:k"), {"k": f"reflection:applied:{week}"})
                s3.commit()
            except Exception:
                try:
                    s3.rollback()
                except Exception:
                    pass


def test_p2_window_mem_expire():
    from app.api.v1 import desktop as desk_mod
    r = client.put("/api/v1/desktop/window-state", json={"width": 1280, "height": 860})
    assert r.status_code == 200, r.text
    r2 = client.get("/api/v1/desktop/window-state")
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"].get("source") == "mem"
    # 过期后不再命中 mem（惰性清回退 db/default）
    try:
        desk_mod._window_state_exp[1] = time.time() - 1
    except Exception:
        pass
    r3 = client.get("/api/v1/desktop/window-state")
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"].get("source") in ("db", "default")
    # 清理
    try:
        desk_mod._window_state_mem.pop(1, None)
        desk_mod._window_state_exp.pop(1, None)
    except Exception:
        pass
