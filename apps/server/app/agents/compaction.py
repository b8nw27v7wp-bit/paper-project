"""Pi compaction 启示：长trace自动压摘要（计数+体量双触发，体量用字符预算近似token）"""

import json
from collections import Counter

THRESHOLD = 20
CHAR_BUDGET = 8000
KEEP_TOKENS = 6000
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


def truncate_head(text, max_lines: int = 2000, max_chars: int = 50000) -> str:
    """Pi truncateHead 对标(harness/utils/truncate.ts)：超限时保留头部前N行/字符（纯函数）。

    行内不切断：按整行累计，无换行可依时在 max_chars 处硬截（单行超长返回头部切片，
    非空串）。调用方传入已按分排序的
    Top hits，保留头部即保留最高分结果。
    """
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    try:
        lines = text.splitlines()
    except Exception:
        return text[:max_chars] if len(text) > max_chars else text
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        text = "\n".join(lines)
    if len(text) > max_chars:
        cut = text.rfind("\n", 0, max_chars)
        text = text[: cut if cut > 0 else max_chars]
    return text


def _is_tool_start(event: dict) -> bool:
    return isinstance(event, dict) and event.get("event") == "tool_call_start"


def _is_tool_end(event: dict) -> bool:
    return isinstance(event, dict) and event.get("event") == "tool_call_end"


def _cut_splits_pair(events: list[dict], cut: int) -> bool:
    """切点是否落在 tool_call_start/end 对中间（相邻成对被切开）。"""
    if 0 < cut < len(events):
        try:
            if _is_tool_start(events[cut - 1]) and _is_tool_end(events[cut]):
                return True
        except (IndexError, AttributeError, TypeError):
            return False
    return False


def _cut_has_dangling(events: list[dict], cut: int) -> bool:
    """切点前后不成对 tool_call_start 悬空（ dropped 有未闭合 start 且 kept 有孤立 end ）。"""
    try:
        dropped = events[:cut]
        kept = events[cut:]
        d_starts = sum(1 for e in dropped if _is_tool_start(e))
        d_ends = sum(1 for e in dropped if _is_tool_end(e))
        k_starts = sum(1 for e in kept if _is_tool_start(e))
        k_ends = sum(1 for e in kept if _is_tool_end(e))
        return (d_starts > d_ends) and (k_ends > k_starts)
    except Exception:
        return False


def find_cut_point(events: list[dict], keep_budget: int = KEEP_TOKENS) -> int:
    """Pi findCutPoint 对标：从尾部累加事件直到 keep 预算，返回切点索引。

    语义：events[:cut] 可压缩，events[cut:] 保留。切点不在 tool_call_start/end
    中间（相邻成对切开或前后悬空时前移一位收敛，保证整对保留在尾部）。
    纯函数，不改 THRESHOLD/CHAR_BUDGET 语义。
    """
    n = len(events)
    if n == 0:
        return 0
    try:
        budget = int(keep_budget)
    except (TypeError, ValueError):
        budget = KEEP_TOKENS
    size = 0
    cut = 0
    for i in range(n - 1, -1, -1):
        try:
            size += event_size(events[i])
        except Exception:
            size += len(str(events[i]))
        if size > budget:
            cut = i + 1
            break
        cut = i
    else:
        cut = 0
    # 切点不在 tool 对中间：前移收敛（保留整对在尾部），至多收敛到 0
    guard = 0
    while 0 < cut < n and guard < n:
        guard += 1
        if _cut_splits_pair(events, cut) or _cut_has_dangling(events, cut):
            cut -= 1
            continue
        break
    if cut < 0:
        cut = 0
    if cut > n:
        cut = n
    return cut


# Pi 驼峰别名（JS 侧 findCutPoint 对标）
findCutPoint = find_cut_point


def _adjust_head_cut(events: list[dict], cut: int) -> int:
    """头切点调整：头部保留前缀， split 时后移一位（整对留在头部）。"""
    n = len(events)
    guard = 0
    while 0 < cut < n and guard < n:
        guard += 1
        if _cut_splits_pair(events, cut) or _cut_has_dangling(events, cut):
            cut += 1
            continue
        break
    return max(0, min(n, cut))


def _adjust_tail_cut(events: list[dict], cut: int) -> int:
    """尾切点调整：尾部保留后缀， split 时前移一位（整对留在尾部）。"""
    n = len(events)
    guard = 0
    while 0 < cut < n and guard < n:
        guard += 1
        if _cut_splits_pair(events, cut) or _cut_has_dangling(events, cut):
            cut -= 1
            continue
        break
    return max(0, min(n, cut))


def summarize(events: list[dict], previous_summary: str | None = None) -> list[dict]:
    """超计数阈值或字符预算时：保头2起步 + findCutPoint 定尾切点，剩余压为1条摘要。

    S8：切点经 find_cut_point 从尾部累加到 KEEP_TOKENS 且不在 tool_call_start/end
    中间（前后悬空前移收敛）；previousSummary 增量叠加（新 text=旧 text+本轮 dist，
    dropped/type_counts 累加）；THRESHOLD/CHAR_BUDGET 触发语义不变。

    纯函数、幂等：未达阈值原样返回；已压缩且无需再压时原样返回，不二次破坏。
    摘要事件名为 thought（8事件契约不变），data.type=compact_summary 标识。
    关键事件保护：approval_required/done 恒不被压（若在中间则钉在尾部之前）。
    """
    if not should_compact(events):
        return list(events)
    # previousSummary 增量叠加：收集旧摘要 text/dropped/type_counts（兼容显式参数）
    prev_texts: list[str] = []
    prev_dropped = 0
    prev_counts: Counter = Counter()
    for e in events:
        if _is_summary(e):
            try:
                d = e.get("data") or {}
                t = str(d.get("text", "") or "")
                if t and t not in prev_texts:
                    prev_texts.append(t)
                prev_dropped += int(d.get("dropped", 0) or 0)
                tc = d.get("type_counts") or {}
                if isinstance(tc, dict):
                    for k, v in tc.items():
                        try:
                            prev_counts[str(k)] += int(v)
                        except (TypeError, ValueError):
                            continue
            except Exception:
                continue
    if isinstance(previous_summary, str) and previous_summary and previous_summary not in prev_texts:
        prev_texts.insert(0, previous_summary)
    elif isinstance(previous_summary, dict):
        try:
            t = str(previous_summary.get("text", "") or "")
            if t and t not in prev_texts:
                prev_texts.insert(0, t)
        except Exception:
            pass
    # 旧摘要不参与本轮切点计算（仅做叠加），切点在剩余事件上求
    rest = [e for e in events if not _is_summary(e)]
    # 全是旧摘要的极端情况：无需再压，原样返回保幂等
    if not rest:
        return list(events)
    n = len(rest)
    if n <= HEAD_KEEP + TAIL_KEEP + 1:
        return list(events)
    # 若剔除旧摘要后已无需压缩（如首轮压后仅追加少量事件），原样返回保幂等
    # 注意：THRESHOLD/CHAR_BUDGET 语义以原始 events 为准（已在入口判定），此处仅防
    # rest 过小导致 head/tail 重叠；不改变触发语义。
    head_n = HEAD_KEEP
    tail_cut = n - TAIL_KEEP
    if total_size(rest) > CHAR_BUDGET:
        # 体量超预算：保头2 + findCutPoint 定尾切点（尾部累加到 KEEP_TOKENS，工具对收敛）
        head_n = _adjust_head_cut(rest, HEAD_KEEP)
        tail_cut = find_cut_point(rest, KEEP_TOKENS)
        # 钳制：至少保留 TAIL_KEEP 尾部、至少留1条可压；钳制后重收敛工具对
        min_tail_cut = n - TAIL_KEEP
        # find_cut_point 返回越大尾越小；若尾不足 TAIL_KEEP 则扩到最小尾
        if tail_cut > min_tail_cut:
            tail_cut = min_tail_cut
        if tail_cut <= head_n:
            tail_cut = min(head_n + 1, n - 1)
        tail_cut = _adjust_tail_cut(rest, tail_cut)
        if tail_cut <= head_n:
            tail_cut = head_n + 1
        if tail_cut > n - 1:
            tail_cut = n - 1
    else:
        # 计数触发：保头2尾2起步，切点避开 tool 对中间
        head_n = _adjust_head_cut(rest, HEAD_KEEP)
        tail_cut = _adjust_tail_cut(rest, n - TAIL_KEEP)
        if head_n >= tail_cut:
            # 调整导致重叠时回退最小保留，保证至少1条可压
            head_n = HEAD_KEEP
            tail_cut = n - TAIL_KEEP
            if head_n >= tail_cut:
                return list(events)
    head = rest[:head_n]
    tail = rest[tail_cut:]
    mid = rest[head_n:tail_cut]
    # 关键事件保护：mid 中的 approval_required/done 钉在尾部之前，不计入 dropped
    _CRITICAL = ("approval_required", "done")
    critical = [e for e in mid if isinstance(e, dict) and e.get("event") in _CRITICAL]
    compressible = [e for e in mid if not (isinstance(e, dict) and e.get("event") in _CRITICAL)]
    counts = Counter(str(e.get("event", "")) for e in compressible if isinstance(e, dict))
    dist = " ".join(f"{k}x{v}" for k, v in sorted(counts.items()))
    cur_text = f"已压缩 {len(compressible)} 条 ({dist})"
    if prev_texts:
        new_text = " | ".join(prev_texts + [cur_text])
    else:
        new_text = cur_text
    merged_counts = dict(prev_counts + counts) if prev_texts else dict(counts)
    merged_dropped = int(prev_dropped + len(compressible)) if prev_texts else len(compressible)
    summary = {
        "event": "thought",
        "data": {
            "agent": "compaction",
            "text": new_text,
            "type": SUMMARY_TYPE,
            "dropped": merged_dropped,
            "type_counts": merged_counts,
        },
    }
    return head + [summary] + critical + tail
