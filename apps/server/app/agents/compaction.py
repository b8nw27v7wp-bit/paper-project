"""Pi compaction 启示：长trace自动压摘要（计数+体量双触发，体量用字符预算近似token）"""

import json
from collections import Counter

THRESHOLD = 20
CHAR_BUDGET = 8000
HEAD_KEEP = 2
TAIL_KEEP = 2
SUMMARY_TYPE = "compact_summary"
_SUMMARY_RESERVE = 256


def event_size(event: dict) -> int:
    """单事件字符量（近似token预算，tiktoken不可用时的保守近似）。"""
    if not isinstance(event, dict):
        return len(str(event))
    try:
        return len(json.dumps(event, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(str(event))


def total_size(events: list[dict]) -> int:
    return sum(event_size(e) for e in events)


def should_compact(events: list[dict]) -> bool:
    if len(events) > THRESHOLD:
        return True
    return total_size(events) > CHAR_BUDGET


def _is_summary(event: dict) -> bool:
    return isinstance(event, dict) and isinstance(event.get("data"), dict) and event["data"].get("type") == SUMMARY_TYPE


def summarize(events: list[dict]) -> list[dict]:
    """超计数阈值或字符预算时：保头2尾2起步，逐步向中间纳入更多头尾直到预算内，剩余压为1条摘要。

    纯函数、幂等：已压缩（含 compact_summary）的序列再次调用原样返回，不二次破坏。
    摘要事件名为 thought（8事件契约不变），data.type=compact_summary 标识，含 dropped 与 type_counts。
    """
    if not should_compact(events):
        return list(events)
    if any(_is_summary(e) for e in events):
        return list(events)
    n = len(events)
    if n <= HEAD_KEEP + TAIL_KEEP + 1:
        return list(events)
    head_n = HEAD_KEEP
    tail_n = TAIL_KEEP
    if total_size(events) > CHAR_BUDGET:
        # 体量超预算：保头2尾2起步，逐步向中间纳入更多头尾直到预算内（剩余至少1条压为摘要）
        size = total_size(events[:head_n]) + total_size(events[n - tail_n:])
        while head_n + tail_n < n - 1:
            add = event_size(events[head_n]) + event_size(events[n - tail_n - 1])
            if size + add + _SUMMARY_RESERVE > CHAR_BUDGET:
                break
            size += add
            head_n += 1
            tail_n += 1
    head = events[:head_n]
    tail = events[n - tail_n:]
    mid = events[head_n:n - tail_n]
    counts = Counter(str(e.get("event", "")) for e in mid if isinstance(e, dict))
    dist = " ".join(f"{k}x{v}" for k, v in sorted(counts.items()))
    summary = {
        "event": "thought",
        "data": {
            "agent": "compaction",
            "text": f"已压缩 {len(mid)} 条 ({dist})",
            "type": SUMMARY_TYPE,
            "dropped": len(mid),
            "type_counts": dict(counts),
        },
    }
    return head + [summary] + tail
