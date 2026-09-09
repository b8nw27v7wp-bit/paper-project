"""checkpoint 完整覆盖（v2.1）：FileMemorySaver 按 thread 分片持久语义。

v2 语义：每 thread 一行（thread_id 主键），put 仅重写本 thread 分片；
兼容读旧 `_all` 单键全量（初始化迁移为分片后删除）；单分片超 1MB 跳过落盘；
总行数超 200 按 updated_at 淘汰最旧。
"""
import pickle
import sqlite3

from app.core.checkpoint import FileMemorySaver


def _saver(tmp_path, name="ck.db"):
    return FileMemorySaver(db_path=tmp_path / name)


def _cp(cid, tasks):
    return {
        "v": 1,
        "id": cid,
        "ts": "2026-09-08T00:00:00+00:00",
        "channel_values": {"tasks": tasks},
        "channel_versions": {"tasks": 1},
        "versions_seen": {},
    }


def _cfg(tid):
    return {"configurable": {"thread_id": tid, "checkpoint_ns": ""}}


def _rows(tmp_path, name="ck.db"):
    conn = sqlite3.connect(str(tmp_path / name))
    try:
        return conn.execute("SELECT thread_id, data FROM checkpoints").fetchall()
    finally:
        conn.close()


def test_put_get_roundtrip(tmp_path):
    s = _saver(tmp_path)
    res = s.put(_cfg("t1"), _cp("cp-1", [{"title": "T"}]), {"source": "test", "step": 1}, {"tasks": 1})
    assert res["configurable"]["checkpoint_id"]
    t = s.get_tuple(_cfg("t1"))
    assert t is not None and t.checkpoint["channel_values"] == {"tasks": [{"title": "T"}]}


def test_put_writes_persists_per_thread(tmp_path):
    s = _saver(tmp_path)
    res = s.put(_cfg("t1"), _cp("cp-1", []), {"source": "test", "step": 1}, {"tasks": 1})
    cfg_w = {"configurable": {"thread_id": "t1", "checkpoint_ns": "", "checkpoint_id": res["configurable"]["checkpoint_id"]}}
    s.put_writes(cfg_w, [("tasks", {"title": "T"})], "task-1")
    rows = dict(_rows(tmp_path))
    assert "t1" in rows and "_all" not in rows
    payload = pickle.loads(rows["t1"])
    assert "storage" in payload and "t1" in payload["storage"]


def test_put_only_rewrites_own_thread(tmp_path):
    s = _saver(tmp_path)
    s.put(_cfg("t1"), _cp("cp-1", [{"title": "A"}]), {"source": "test", "step": 1}, {"tasks": 1})
    before = dict(_rows(tmp_path))["t1"]
    s.put(_cfg("t2"), _cp("cp-2", [{"title": "B"}]), {"source": "test", "step": 1}, {"tasks": 1})
    after = dict(_rows(tmp_path))
    # t2 落盘不改写 t1 分片（O(单trace)而非 O(全库)）
    assert after["t1"] == before
    assert "t2" in after


def test_restart_recovery(tmp_path):
    s = _saver(tmp_path)
    s.put(_cfg("t1"), _cp("cp-1", [{"title": "Persist"}]), {"source": "test", "step": 1}, {"tasks": 1})
    s2 = _saver(tmp_path)  # 模拟重启：新实例从文件恢复
    t = s2.get_tuple(_cfg("t1"))
    assert t is not None and t.checkpoint["channel_values"] == {"tasks": [{"title": "Persist"}]}


def test_thread_isolation(tmp_path):
    s = _saver(tmp_path)
    s.put(_cfg("tA"), _cp("cp-A", [{"title": "A"}]), {"source": "test", "step": 1}, {"tasks": 1})
    s.put(_cfg("tB"), _cp("cp-B", [{"title": "B"}]), {"source": "test", "step": 1}, {"tasks": 1})
    ta = s.get_tuple(_cfg("tA"))
    tb = s.get_tuple(_cfg("tB"))
    assert ta.checkpoint["id"] == "cp-A" and tb.checkpoint["id"] == "cp-B"
    # 重启后隔离仍成立
    s2 = _saver(tmp_path)
    assert s2.get_tuple(_cfg("tA")).checkpoint["id"] == "cp-A"
    assert s2.get_tuple(_cfg("tB")).checkpoint["id"] == "cp-B"


def test_legacy_all_migrated(tmp_path):
    s = _saver(tmp_path)
    s.put(_cfg("t1"), _cp("cp-1", [{"title": "Good"}]), {"source": "test", "step": 1}, {"tasks": 1})
    # 用真实内存结构拼旧格式 _all 全量（保证内部元组格式真实）+ 脏行
    legacy = {
        "storage": {"t1": dict(s.storage["t1"]), "t9": dict(s.storage["t1"])},
        "writes": dict(s.writes),
        "blobs": dict(s.blobs),
    }
    conn = sqlite3.connect(str(tmp_path / "ck.db"))
    try:
        conn.execute("DELETE FROM checkpoints")
        conn.execute("INSERT OR REPLACE INTO checkpoints (thread_id, data) VALUES (?, ?)", ("_all", pickle.dumps(legacy)))
        conn.execute("INSERT OR REPLACE INTO checkpoints (thread_id, data) VALUES (?, ?)", ("junk", b"\x00\x01not-pickle"))
        conn.commit()
    finally:
        conn.close()
    s2 = _saver(tmp_path)
    rows = dict(_rows(tmp_path))
    # _all 已迁移删除，脏行被跳过，旧线程可恢复
    assert "_all" not in rows
    assert "junk" in rows  # 脏行保留但读取跳过
    t = s2.get_tuple({"configurable": {"thread_id": "t9", "checkpoint_ns": ""}})
    assert t is not None and t.checkpoint["id"] == "cp-1"
    t1 = s2.get_tuple(_cfg("t1"))
    assert t1 is not None and t1.checkpoint["id"] == "cp-1"


def test_dirty_rows_skipped(tmp_path):
    s = _saver(tmp_path)
    s.put(_cfg("t1"), _cp("cp-1", [{"title": "Good"}]), {"source": "test", "step": 1}, {"tasks": 1})
    conn = sqlite3.connect(str(tmp_path / "ck.db"))
    try:
        conn.execute("INSERT OR REPLACE INTO checkpoints (thread_id, data) VALUES (?, ?)", ("junk", b"\x00\x01not-pickle"))
        conn.commit()
    finally:
        conn.close()
    s2 = _saver(tmp_path)
    t = s2.get_tuple(_cfg("t1"))
    assert t is not None and t.checkpoint["channel_values"] == {"tasks": [{"title": "Good"}]}
