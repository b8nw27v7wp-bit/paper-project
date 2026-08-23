"""Pi compaction 启示：长trace自动压摘要"""
from typing import List, Dict

THRESHOLD = 20

def should_compact(events: List[Dict]) -> bool:
    return len(events) > THRESHOLD

def summarize(events: List[Dict]) -> List[Dict]:
    # 保留首 thought + 末 done，中间压为1条摘要
    if not should_compact(events):
        return events
    head = events[:2]
    tail = events[-2:]
    mid = events[2:-2]
    task_n = sum(1 for e in mid if e.get("event") == "task_created")
    tool_n = sum(1 for e in mid if e.get("event") == "tool_call")
    summary = {"event": "thought", "data": {"agent": "compaction", "text": f"已压缩 {len(mid)} 条 (工具{tool_n}/任务{task_n})"}}
    return head + [summary] + tail
