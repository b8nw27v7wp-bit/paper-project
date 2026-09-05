import json

from app.agents import compaction
from app.agents.compaction import CHAR_BUDGET, THRESHOLD, should_compact, summarize


def _events(n, blob="x" * 20):
    evs = [{"event": "thought", "data": {"agent": "planner", "text": "start " + blob}}]
    for i in range(max(0, n - 4)):
        evs.append({"event": "tool_call", "data": {"tool": f"t{i}", "args": {"blob": blob, "i": i}}})
    evs.append({"event": "mentor_msg", "data": {"text": "hi " + blob}})
    evs.append({"event": "reflector_patch", "data": {"patch": {}}})
    evs.append({"event": "done", "data": {"trace_id": "t" * 32, "count": 1, "source": "mock", "rewrites": 0}})
    return evs


def test_under_threshold_unchanged():
    evs = _events(10)
    assert not should_compact(evs)
    assert summarize(evs) == evs


def test_count_trigger():
    evs = _events(THRESHOLD + 5)
    assert should_compact(evs)
    out = summarize(evs)
    assert len(out) < len(evs)
    assert out[0] is evs[0]
    assert out[0]["event"] == "thought"
    assert out[-1]["event"] == "done"
    assert out[-1] is evs[-1]
    summary = [e for e in out if isinstance(e.get("data"), dict) and e["data"].get("type") == "compact_summary"]
    assert len(summary) == 1
    s = summary[0]["data"]
    assert s["dropped"] == len(evs) - 4
    assert "tool_call" in s["type_counts"]
    assert s["type_counts"]["tool_call"] == s["dropped"] - 1
    assert "mentor_msg" in s["type_counts"]
    assert len(out) == 5


def test_budget_trigger(monkeypatch):
    monkeypatch.setattr(compaction, "THRESHOLD", 10**9)
    blob = "x" * 1000
    evs = _events(12, blob=blob)
    assert len(evs) <= THRESHOLD
    assert compaction.total_size(evs) > CHAR_BUDGET
    assert should_compact(evs)
    out = summarize(evs)
    assert compaction.total_size(out) < compaction.total_size(evs)
    assert compaction.total_size(out) <= CHAR_BUDGET + 512
    assert out[-1]["event"] == "done"
    summary = [e for e in out if isinstance(e.get("data"), dict) and e["data"].get("type") == "compact_summary"]
    assert len(summary) == 1
    assert summary[0]["data"]["dropped"] >= 1


def test_idempotent():
    evs = _events(THRESHOLD + 10)
    once = summarize(evs)
    twice = summarize(once)
    assert twice == once
    assert json.dumps(twice, ensure_ascii=False) == json.dumps(once, ensure_ascii=False)


def test_event_types_not_lost():
    evs = _events(THRESHOLD + 10)
    out = summarize(evs)
    assert out[-1]["event"] == "done"
    assert any(e["event"] == "thought" for e in out)
    assert any(e["event"] == "tool_call" for e in out)
    # 中间被压类型不丢：要么保留原事件，要么计入摘要 type_counts
    summary = next(e["data"] for e in out if isinstance(e.get("data"), dict) and e["data"].get("type") == "compact_summary")
    kept = {e["event"] for e in out}
    counted = set(summary["type_counts"])
    for ev in {e["event"] for e in evs}:
        assert ev in kept or ev in counted, ev


def test_tiny_sequence_no_compact():
    evs = _events(3)
    assert summarize(evs) == evs
