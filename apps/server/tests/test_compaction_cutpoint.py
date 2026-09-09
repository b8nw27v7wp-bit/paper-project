"""S8 切点用例：不切 tool 对中间 / previousSummary 增量叠加"""

from app.agents.compaction import THRESHOLD, find_cut_point, summarize


def _events(n, blob="x" * 20):
    evs = [{"event": "thought", "data": {"agent": "planner", "text": "start " + blob}}]
    for i in range(max(0, n - 4)):
        evs.append({"event": "tool_call", "data": {"tool": f"t{i}", "args": {"blob": blob, "i": i}}})
    evs.append({"event": "mentor_msg", "data": {"text": "hi " + blob}})
    evs.append({"event": "reflector_patch", "data": {"patch": {}}})
    evs.append({"event": "done", "data": {"trace_id": "t" * 32, "count": 1, "source": "mock", "rewrites": 0}})
    return evs


def _is_start(e):
    return isinstance(e, dict) and e.get("event") == "tool_call_start"


def _is_end(e):
    return isinstance(e, dict) and e.get("event") == "tool_call_end"


def test_cutpoint_not_split_tool_pair():
    # 构造 25 事件，朴素尾2切点(23)恰落在 start(22)/end(23) 中间
    n = THRESHOLD + 5
    evs = _events(n)
    assert len(evs) == n
    # 在 mid 尾 / tail 头边界埋一对 tool_call_start/end
    evs[n - 3] = {"event": "tool_call_start", "data": {"tool": "researcher", "id": "a1"}}
    evs[n - 2] = {"event": "tool_call_end", "data": {"tool": "researcher", "id": "a1"}}
    # find_cut_point 在该预算下不应返回分裂切点：直接校验相邻分裂收敛
    # 用精确预算 forcing 切点落在对中间，再看是否前移收敛
    from app.agents.compaction import event_size

    # 计算使朴素切点= n-2 的预算（保留 end 及之后，不含 start）
    keep_end_only = sum(event_size(e) for e in evs[n - 2 :])
    # 取两者之间的预算，朴素会切在对中间
    budget = keep_end_only
    cut = find_cut_point(evs, budget)
    assert cut != n - 2, f"切点不应落在 tool 对中间，got cut={cut}"
    # summarize 端到端：输出不应出现孤立 end（有 end 无 start 即分裂）
    out = summarize(evs)
    starts = sum(1 for e in out if _is_start(e))
    ends = sum(1 for e in out if _is_end(e))
    # 整对要么同保留（starts==1 and ends==1），要么同被压（均为0，计入摘要）
    assert (starts, ends) in ((0, 0), (1, 1)), f"tool 对被切散 starts={starts} ends={ends}"
    # 若同被压，摘要 type_counts 应计入；若同保留，尾部应含整对
    if (starts, ends) == (0, 0):
        s = next(e["data"] for e in out if isinstance(e.get("data"), dict) and e["data"].get("type") == "compact_summary")
        assert "tool_call_start" in s["type_counts"] or "tool_call_end" in s["type_counts"]


def test_previous_summary_stacking():
    evs = _events(THRESHOLD + 5)
    once = summarize(evs)
    old = next(e["data"] for e in once if isinstance(e.get("data"), dict) and e["data"].get("type") == "compact_summary")
    old_text = old["text"]
    assert old_text
    # 在旧摘要基础上追加足够多新事件（插在 done 之前），触发二次压缩
    new_events = [
        {"event": "tool_call", "data": {"tool": f"new{i}", "args": {"i": i}}}
        for i in range(THRESHOLD + 5)
    ]
    combined = once[:-1] + new_events + once[-1:]
    twice = summarize(combined)
    assert len(twice) < len(combined)
    new = next(e["data"] for e in twice if isinstance(e.get("data"), dict) and e["data"].get("type") == "compact_summary")
    # 增量叠加：新摘要 text 含旧摘要 text + 本轮 dist
    assert old_text in new["text"], f"新摘要应叠加旧摘要，got {new['text'][:200]}"
    assert new["dropped"] >= old["dropped"] + 1
