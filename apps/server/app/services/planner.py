import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger("app.planner")

# TTL 三轨统一（P2-BE）：PlanStore 内存 TTL 3600，与 plans.py PLAN_STORE_TTL 同值；惰性清理只加过期淘汰不改行为
PLAN_STORE_TTL = 3600
_PLAN_STORE_CAP = 500

# P2 幂等键注册表：patch_id 已见即复用短路（内存去重，防重复重分配抖动）
# 注意：进程级全局（非按trace隔离），reflector uuid唯一故生产无碰撞；单测复用固定
# patch_id 时须调 clear_seen_patch_ids() 隔离（对标 registry hook 表隔离）。
_SEEN_PATCH_IDS: set[str] = set()


def clear_seen_patch_ids() -> None:
    """清空 patch_id 幂等注册表（单测隔离/进程长期运行瘦身，新增不改旧语义）。"""
    _SEEN_PATCH_IDS.clear()

# S2: 最近一次 llm_generate 的 meta（finish_reason 透出，供 graph planner_node 判断截断）
LAST_LLM_META: dict = {}


# ===== P1 真重分配：reflector patch 可执行落地（纯函数，便于单测）=====
# 截断语义（选其一并注释写明）：采用“移入下一周 + 加 note，status 不变”，绝不删除任务。
# 即重分配后仍超载时，将最低优先级任务整体搬至 +7 天同时间段，并在 task["note"] 中标记
# “超载截断/顺延”字样；若 task 已有 status 字段则原样保留。critic 下一轮按新日期校验，
# 不会误判任务丢失。单任务自身时长即超标时无法靠搬移消解，则仅加 note 标记后保留。
# 优先级语义：priority 数值越大优先级越高（与 mock_generate 4>3 一致），最低优先级=数值最小。
# 可用时长：preferences.hours_per_day（1-8），缺省/非法回退 4.0（与 critic 单日≤4h 对齐）。
# 缓冲默认 15min，仅当 patch 含 add_buffer 时强制同日任务间隙；未知 patch 键直接忽略。
def _parse_task_dt(v: object) -> datetime | None:
    try:
        if isinstance(v, datetime):
            d = v
        elif isinstance(v, str) and v.strip():
            s = v.strip()
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            d = datetime.fromisoformat(s)
        else:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d
    except (TypeError, ValueError):
        return None


def _available_hours(preferences: dict | None) -> float:
    try:
        h = float((preferences or {}).get("hours_per_day", 4))
    except (TypeError, ValueError):
        return 4.0
    if h < 1 or h > 8:
        return 4.0
    return h


def _resolve_buffer_minutes(patch: dict | None, preferences: dict | None) -> float:
    if not isinstance(patch, dict) or not patch.get("add_buffer"):
        return 0.0
    ab = patch.get("add_buffer")
    if isinstance(ab, (int, float)) and not isinstance(ab, bool):
        try:
            return max(5.0, min(60.0, float(ab)))
        except (TypeError, ValueError):
            pass
    if isinstance(ab, dict):
        for k in ("minutes", "buffer_minutes", "gap"):
            try:
                if k in ab:
                    return max(5.0, min(60.0, float(ab[k])))
            except (TypeError, ValueError):
                continue
    for k in ("buffer_minutes", "buffer", "gap_minutes"):
        try:
            if isinstance(patch.get(k), (int, float)) and not isinstance(patch.get(k), bool):
                return max(5.0, min(60.0, float(patch[k])))
            if isinstance(preferences, dict) and isinstance(preferences.get(k), (int, float)) and not isinstance(preferences.get(k), bool):
                return max(5.0, min(60.0, float(preferences[k])))
        except (TypeError, ValueError):
            continue
    return 15.0


def _normalize_realloc_list(v: object) -> list[dict]:
    items = v if isinstance(v, list) else [v]
    out: list[dict] = []
    for it in items:
        if isinstance(it, dict) and it.get("from") and it.get("to"):
            try:
                hrs = float(it.get("hours", 0) or 0)
            except (TypeError, ValueError):
                hrs = 0.0
            if hrs <= 0:
                continue
            out.append({"from": str(it["from"])[:10], "to": str(it["to"])[:10], "hours": hrs})
    return out


def _task_duration_hours(s: datetime, e: datetime) -> float:
    try:
        return max(0.0, (e - s).total_seconds() / 3600)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def apply_patch_reallocation(tasks: list[dict], patch: dict | None, preferences: dict | None) -> list[dict]:
    """按 patch 语义逐项落地重分配的纯函数（无 IO/无副作用，不改输入）。

    输入 tasks（含 planned_start/planned_end ISO 字符串）、patch（reduce_load/add_buffer/
    reorder/reallocate/truncate 等）、preferences（含 hours_per_day），输出新 tasks 列表
    （按 planned_start 排序，时长保持，绝不删除任务）。
    空 patch / {"keep": True} 直接返回深拷贝（调用方保留旧 +30min 平移即为旧行为）。
    顺序：reallocate → reduce_load → reorder → add_buffer → 超载截断兜底。
    P2 幂等：patch 含 patch_id 且已见过时直接返回深拷贝（排序语义不变，不做二次重分配）。
    注意幂等注册表为进程级全局副作用（非纯函数部分），跨 trace 同 id 会短路。
    """
    import copy as _copy

    if not isinstance(tasks, list):
        return []
    # P2 patch_id 幂等（不改排序/截断语义：正常路径原样，重复键短路返回排序深拷贝）
    try:
        _pid = patch.get("patch_id") if isinstance(patch, dict) else None
        if isinstance(_pid, str) and _pid:
            if _pid in _SEEN_PATCH_IDS:
                _dup = _copy.deepcopy(tasks)
                try:
                    return sorted(
                        _dup,
                        key=lambda t: str(t.get("planned_start", "")) if isinstance(t, dict) else "",
                    ) if _dup else []
                except (TypeError, ValueError):
                    return _dup
            if len(_SEEN_PATCH_IDS) > 5000:
                _SEEN_PATCH_IDS.clear()
            _SEEN_PATCH_IDS.add(_pid)
    except Exception:
        pass
    new_tasks: list[dict] = _copy.deepcopy(tasks)
    if not isinstance(patch, dict) or not patch or patch.get("keep") is True:
        return sorted(
            new_tasks,
            key=lambda t: str(t.get("planned_start", "")) if isinstance(t, dict) else "",
        ) if new_tasks else []
    prefs = preferences if isinstance(preferences, dict) else {}
    available = _available_hours(prefs)
    buf_min = _resolve_buffer_minutes(patch, prefs)
    buf_h = buf_min / 60.0

    def _day_loads(ts: list[dict]) -> dict[str, float]:
        loads: dict[str, float] = {}
        for t in ts:
            if not isinstance(t, dict):
                continue
            s = _parse_task_dt(t.get("planned_start"))
            e = _parse_task_dt(t.get("planned_end"))
            if s is None or e is None:
                continue
            loads[s.date().isoformat()] = loads.get(s.date().isoformat(), 0.0) + _task_duration_hours(s, e)
        return loads

    def _max_end_on_day(ts: list[dict], day: str) -> datetime | None:
        best: datetime | None = None
        for t in ts:
            if not isinstance(t, dict):
                continue
            s = _parse_task_dt(t.get("planned_start"))
            e = _parse_task_dt(t.get("planned_end"))
            if s is None or e is None or s.date().isoformat() != day:
                continue
            if best is None or e > best:
                best = e
        return best

    def _place_after(day: str, after: datetime | None, dur_h: float, ref_tz) -> tuple[datetime, datetime]:
        try:
            base_day = datetime.fromisoformat(day).date()
        except (TypeError, ValueError):
            base_day = (after.date() if after is not None else datetime.now(UTC).date())
        tz = ref_tz if ref_tz is not None else UTC
        if after is None:
            start = datetime(base_day.year, base_day.month, base_day.day, 9, 0, tzinfo=tz)
        else:
            start = after + timedelta(hours=buf_h if buf_min > 0 else 0.0)
            # 跨天溢出时仍钳回目标日 09:00+当日负荷，避免日期漂移不可控
            if start.date().isoformat() != day:
                start = datetime(base_day.year, base_day.month, base_day.day, 9, 0, tzinfo=tz)
                me = _max_end_on_day(new_tasks, day)
                if me is not None:
                    start = me + timedelta(hours=buf_h if buf_min > 0 else 0.0)
                    if start.date().isoformat() != day:
                        start = datetime(base_day.year, base_day.month, base_day.day, 9, 0, tzinfo=tz)
        end = start + timedelta(hours=dur_h)
        return start, end

    # 1) reallocate：跨日/跨周搬移（最低优先级优先，最多搬 hours）
    realloc_raw = patch.get("reallocate")
    if isinstance(realloc_raw, (dict, list)) and realloc_raw:
        for item in _normalize_realloc_list(realloc_raw):
            fday, tday, need = item["from"], item["to"], item["hours"]
            if fday == tday:
                continue
            idxs = [i for i, t in enumerate(new_tasks) if isinstance(t, dict) and _parse_task_dt(t.get("planned_start")) is not None and _parse_task_dt(t.get("planned_start")).date().isoformat() == fday and _parse_task_dt(t.get("planned_end")) is not None]
            # 最低优先级优先，同级按时长短优先（少搬多任务更易凑满 hours）
            def _rk(i: int) -> tuple:
                t = new_tasks[i]
                try:
                    pri = int(t.get("priority", 3))
                except (TypeError, ValueError):
                    pri = 3
                s = _parse_task_dt(t.get("planned_start"))
                e = _parse_task_dt(t.get("planned_end"))
                return (pri, _task_duration_hours(s, e) if s and e else 0.0)
            idxs.sort(key=_rk)
            moved = 0.0
            for i in idxs:
                if moved >= need - 1e-9:
                    break
                t = new_tasks[i]
                s = _parse_task_dt(t.get("planned_start"))
                e = _parse_task_dt(t.get("planned_end"))
                if s is None or e is None:
                    continue
                dur = _task_duration_hours(s, e)
                if dur <= 0:
                    continue
                me = _max_end_on_day(new_tasks, tday)
                ns, ne = _place_after(tday, me, dur, s.tzinfo)
                t["planned_start"] = ns.isoformat()
                t["planned_end"] = ne.isoformat()
                t["date"] = ns.date().isoformat()
                moved += dur

    # 2) reduce_load：超负荷日（>可用时长）的任务按优先级向后顺延到有空闲的日子
    wants_reduce = bool(patch.get("reduce_load") or patch.get("reduce_daily_hours") or patch.get("reduce_weekly") or patch.get("truncate"))
    if wants_reduce:
        for _round in range(max(1, len(new_tasks))):
            loads = _day_loads(new_tasks)
            over = sorted([d for d, h in loads.items() if h - available > 1e-9])
            if not over:
                break
            progressed = False
            for d in over:
                loads = _day_loads(new_tasks)
                if loads.get(d, 0.0) - available <= 1e-9:
                    continue
                idxs = [i for i, t in enumerate(new_tasks) if isinstance(t, dict) and _parse_task_dt(t.get("planned_start")) is not None and _parse_task_dt(t.get("planned_start")).date().isoformat() == d and _parse_task_dt(t.get("planned_end")) is not None]
                if not idxs:
                    continue
                def _rk2(i: int) -> tuple:
                    t = new_tasks[i]
                    try:
                        pri = int(t.get("priority", 3))
                    except (TypeError, ValueError):
                        pri = 3
                    s = _parse_task_dt(t.get("planned_start"))
                    return (pri, -(s.timestamp() if s else 0.0))
                idxs.sort(key=_rk2)
                cand = idxs[0]
                t = new_tasks[cand]
                s = _parse_task_dt(t.get("planned_start"))
                e = _parse_task_dt(t.get("planned_end"))
                if s is None or e is None:
                    continue
                dur = _task_duration_hours(s, e)
                # 找随后 14 天内首个有空闲的日子
                target: str | None = None
                try:
                    base = datetime.fromisoformat(d).date()
                except (TypeError, ValueError):
                    base = s.date()
                loads_now = _day_loads(new_tasks)
                for k in range(1, 15):
                    dd = (base + timedelta(days=k)).isoformat()
                    if loads_now.get(dd, 0.0) + dur - available <= 1e-9:
                        target = dd
                        break
                if target is None:
                    target = (base + timedelta(days=1)).isoformat()
                me = _max_end_on_day(new_tasks, target)
                ns, ne = _place_after(target, me, dur, s.tzinfo)
                t["planned_start"] = ns.isoformat()
                t["planned_end"] = ne.isoformat()
                t["date"] = ns.date().isoformat()
                progressed = True
                break
            if not progressed:
                break

    # 3) reorder：按 patch 指定顺序重排同日任务起止（时长保持，从 09:00 顺序排布消解重叠）
    ro = patch.get("reorder")
    if ro:
        order_list: list[str] = []
        if isinstance(ro, list):
            order_list = [str(x) for x in ro if str(x)]
        elif isinstance(ro, dict):
            for k in ("order", "titles", "sequence"):
                v = ro.get(k)
                if isinstance(v, list) and v:
                    order_list = [str(x) for x in v if str(x)]
                    break
        # 按日起止重排
        days = sorted({_parse_task_dt(t.get("planned_start")).date().isoformat() for t in new_tasks if isinstance(t, dict) and _parse_task_dt(t.get("planned_start")) is not None})
        for d in days:
            idxs = [i for i, t in enumerate(new_tasks) if isinstance(t, dict) and _parse_task_dt(t.get("planned_start")) is not None and _parse_task_dt(t.get("planned_start")).date().isoformat() == d]
            if len(idxs) < 2:
                continue
            if order_list:
                pos = {name: k for k, name in enumerate(order_list)}
                def _ok(i: int) -> tuple:
                    title = str(new_tasks[i].get("title", ""))
                    best = len(order_list)
                    for name, k in pos.items():
                        if title == name or (name and (name in title or title in name)):
                            best = k
                            break
                    s = _parse_task_dt(new_tasks[i].get("planned_start"))
                    return (best, s.timestamp() if s else 0.0)
                idxs.sort(key=_ok)
            else:
                def _pk(i: int) -> tuple:
                    try:
                        pri = int(new_tasks[i].get("priority", 3))
                    except (TypeError, ValueError):
                        pri = 3
                    s = _parse_task_dt(new_tasks[i].get("planned_start"))
                    return (-pri, s.timestamp() if s else 0.0)
                idxs.sort(key=_pk)
            try:
                base = datetime.fromisoformat(d).date()
            except (TypeError, ValueError):
                continue
            ref = _parse_task_dt(new_tasks[idxs[0]].get("planned_start"))
            tz = ref.tzinfo if ref is not None else UTC
            cur = datetime(base.year, base.month, base.day, 9, 0, tzinfo=tz)
            for i in idxs:
                t = new_tasks[i]
                s = _parse_task_dt(t.get("planned_start"))
                e = _parse_task_dt(t.get("planned_end"))
                if s is None or e is None:
                    continue
                dur = _task_duration_hours(s, e)
                ne = cur + timedelta(hours=dur)
                t["planned_start"] = cur.isoformat()
                t["planned_end"] = ne.isoformat()
                t["date"] = cur.date().isoformat()
                cur = ne

    # 4) add_buffer：任务间插入缓冲（默认 15min），同日按起止顺延消解重叠
    if buf_min > 0:
        days = sorted({_parse_task_dt(t.get("planned_start")).date().isoformat() for t in new_tasks if isinstance(t, dict) and _parse_task_dt(t.get("planned_start")) is not None})
        for d in days:
            idxs = [i for i, t in enumerate(new_tasks) if isinstance(t, dict) and _parse_task_dt(t.get("planned_start")) is not None and _parse_task_dt(t.get("planned_start")).date().isoformat() == d and _parse_task_dt(t.get("planned_end")) is not None]
            if len(idxs) < 2:
                continue
            idxs.sort(key=lambda i: _parse_task_dt(new_tasks[i].get("planned_start")).timestamp())  # type: ignore[union-attr]
            prev_end: datetime | None = None
            for i in idxs:
                t = new_tasks[i]
                s = _parse_task_dt(t.get("planned_start"))
                e = _parse_task_dt(t.get("planned_end"))
                if s is None or e is None:
                    continue
                dur = _task_duration_hours(s, e)
                if prev_end is not None:
                    need_start = prev_end + timedelta(minutes=buf_min)
                    if s < need_start:
                        s = need_start
                        e = s + timedelta(hours=dur)
                        t["planned_start"] = s.isoformat()
                        t["planned_end"] = e.isoformat()
                        t["date"] = s.date().isoformat()
                prev_end = _parse_task_dt(t.get("planned_end"))

    # 5) 截断兜底：仍超载则将最低优先级任务移入下一周（+7天）并加 note，status 不变，绝不删除
    for _round in range(max(1, len(new_tasks))):
        loads = _day_loads(new_tasks)
        over = sorted([d for d, h in loads.items() if h - available > 1e-9])
        if not over:
            break
        progressed = False
        for d in over:
            idxs = [i for i, t in enumerate(new_tasks) if isinstance(t, dict) and _parse_task_dt(t.get("planned_start")) is not None and _parse_task_dt(t.get("planned_start")).date().isoformat() == d and _parse_task_dt(t.get("planned_end")) is not None]
            if not idxs:
                continue
            def _rk3(i: int) -> tuple:
                t = new_tasks[i]
                try:
                    pri = int(t.get("priority", 3))
                except (TypeError, ValueError):
                    pri = 3
                s = _parse_task_dt(t.get("planned_start"))
                e = _parse_task_dt(t.get("planned_end"))
                dur = _task_duration_hours(s, e) if s and e else 0.0
                return (pri, -dur)
            idxs.sort(key=_rk3)
            # 单任务自身超标：仅标记不搬移（搬了下周同样超标，来回抖动），保留并加 note
            if len(idxs) == 1:
                t = new_tasks[idxs[0]]
                s = _parse_task_dt(t.get("planned_start"))
                e = _parse_task_dt(t.get("planned_end"))
                dur = _task_duration_hours(s, e) if s and e else 0.0
                if dur - available > 1e-9:
                    note = str(t.get("note", ""))
                    tag = f"超载截断：单任务{dur:.1f}h>可用{available:.0f}h，已标记保留，status不变"
                    if "超载截断" not in note:
                        t["note"] = (note + "；" if note else "") + tag
                    break
            cand = idxs[0]
            t = new_tasks[cand]
            s = _parse_task_dt(t.get("planned_start"))
            e = _parse_task_dt(t.get("planned_end"))
            if s is None or e is None:
                continue
            dur = _task_duration_hours(s, e)
            ns = s + timedelta(days=7)
            ne = e + timedelta(days=7)
            t["planned_start"] = ns.isoformat()
            t["planned_end"] = ne.isoformat()
            t["date"] = ns.date().isoformat()
            note = str(t.get("note", ""))
            tag = f"超载截断：{d}负荷{loads.get(d, 0.0):.1f}h>可用{available:.0f}h，已顺延至下周{ns.date().isoformat()}，status不变"
            if "超载截断" not in note:
                t["note"] = (note + "；" if note else "") + tag
            progressed = True
            break
        if not progressed:
            break
    try:
        return sorted(new_tasks, key=lambda t: str(t.get("planned_start", "")) if isinstance(t, dict) else "")
    except (TypeError, ValueError):
        return new_tasks


# 内存 SSE 重放存储（Pi SessionState 启示：内存 + DB 回退）
class PlanStore(dict):  # type: ignore
    """内存 + DB 双写，回退重建（对标 Pi/packages/agent/src/harness/session/memory.ts + state.ts）"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # P2-BE：TTL 惰性清理（单键 exp，不改既有 put/get 语义，过期视为不存在走 DB 重建）
        try:
            object.__setattr__(self, "_exp", {})
        except Exception:
            try:
                self.__dict__["_exp"] = {}
            except Exception:
                pass

    def _exp_map(self) -> dict:
        try:
            m = object.__getattribute__(self, "_exp")
            if isinstance(m, dict):
                return m
        except Exception:
            pass
        try:
            m2 = self.__dict__.get("_exp")
            if isinstance(m2, dict):
                return m2
        except Exception:
            pass
        return {}

    def _is_expired(self, trace_id: str) -> bool:
        try:
            exp = self._exp_map().get(trace_id)
            if exp is None:
                return False
            return float(exp) <= time.time()
        except Exception:
            return False

    def _purge_expired(self) -> None:
        try:
            now = time.time()
            for k in [k for k, e in list(self._exp_map().items()) if float(e or 0) <= now]:
                try:
                    super().pop(k, None)
                except Exception:
                    pass
                try:
                    self._exp_map().pop(k, None)
                except Exception:
                    pass
        except Exception:
            pass

    def purge_expired(self) -> int:
        """公开清扫入口（单测/运维用）：返回清理数，语义只删过期键。"""
        try:
            before = len(self._exp_map())
            self._purge_expired()
            return max(0, before - len(self._exp_map()))
        except Exception:
            return 0

    def put(self, trace_id: str, events: list[dict], session=None) -> None:
        try:
            self._purge_expired()
        except Exception:
            pass
        self[trace_id] = events
        try:
            self._exp_map()[trace_id] = time.time() + PLAN_STORE_TTL
        except Exception:
            pass
        # 若提供 session，可选落库 AgentRunLog 供重启恢复（plans.py 已在 multi 模式写入，此处兼容 single）
        if session is not None:
            try:
                from app.models.log import AgentRunLog

                # 避免重复：若已存在 trace_id 则跳过
                from sqlmodel import select

                exists = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id)).first()
                if not exists:
                    # 将 events 完整落库（供重启后无损重建）
                    log = AgentRunLog(
                        trace_id=trace_id,
                        agent_name="planner",
                        input={"trace_id": trace_id},
                        output={"events": events},
                        tool_calls=[{"tool": "plan_store_put"}],
                    )
                    session.add(log)
                    session.commit()
            except Exception:
                logger.warning("plan_store.put DB persist failed: trace_id=%s", trace_id, exc_info=True)

    def __setitem__(self, key, value):
        # P2-BE：直写 _ps[trace]=events 同样带 TTL（与 put 同值，不改覆盖语义）
        try:
            super().__setitem__(key, value)
        except Exception:
            return
        try:
            if isinstance(key, str):
                self._exp_map()[key] = time.time() + PLAN_STORE_TTL
                # 惰性清过期（超 cap 时 plans.py 侧已有 LRU，此处仅清过期不截断）
                self._purge_expired()
        except Exception:
            pass

    def __contains__(self, key) -> bool:
        try:
            if super().__contains__(key):
                if isinstance(key, str) and self._is_expired(key):
                    try:
                        super().pop(key, None)
                    except Exception:
                        pass
                    try:
                        self._exp_map().pop(key, None)
                    except Exception:
                        pass
                    return False
                return True
            return False
        except Exception:
            try:
                return super().__contains__(key)
            except Exception:
                return False

    def get(self, key, default=None):
        try:
            if isinstance(key, str) and self._is_expired(key):
                try:
                    super().pop(key, None)
                except Exception:
                    pass
                try:
                    self._exp_map().pop(key, None)
                except Exception:
                    pass
                return default
            return super().get(key, default)
        except Exception:
            try:
                return super().get(key, default)
            except Exception:
                return default

    def pop(self, key, *args):
        try:
            self._exp_map().pop(key, None)
        except Exception:
            pass
        try:
            return super().pop(key, *args)
        except Exception:
            if args:
                return args[0]
            raise

    def get_or_reconstruct(self, trace_id: str, session=None) -> list[dict] | None:
        # P2-BE：过期视为不存在（惰性清），走 DB 重建路径；未过期直接命中
        try:
            self._purge_expired()
        except Exception:
            pass
        try:
            if self._is_expired(trace_id):
                try:
                    super().pop(trace_id, None)
                except Exception:
                    pass
                try:
                    self._exp_map().pop(trace_id, None)
                except Exception:
                    pass
            elif super().__contains__(trace_id):
                try:
                    return super().__getitem__(trace_id)  # type: ignore
                except Exception:
                    pass
        except Exception:
            pass
        if session is None:
            try:
                return super().get(trace_id)  # type: ignore
            except Exception:
                return None
        try:
            from sqlmodel import select

            from app.models.log import AgentRunLog

            logs = session.exec(select(AgentRunLog).where(AgentRunLog.trace_id == trace_id).order_by(AgentRunLog.created_at)).all()  # type: ignore
            if not logs:
                return None
            # 重建简化事件（对标 Pi deriveSessionContextState + sessionEntryToContextMessages）
            events: list[dict] = []
            for log in logs:
                out = getattr(log, "output", {}) or {}
                # 若 output 含 events，直接复用
                if isinstance(out, dict) and "events" in out and isinstance(out["events"], list):
                    events = out["events"]  # type: ignore
                    break
            if not events:
                # 降级：基于 planner 的 tasks 重建
                planner_log = next((l for l in logs if getattr(l, "agent_name", "") == "planner"), logs[0])
                out = getattr(planner_log, "output", {}) or {}
                tasks_raw = out.get("tasks", []) if isinstance(out, dict) else []
                events.append({"event": "thought", "data": {"agent": "planner", "text": "从DB恢复的规划轨迹..."}})
                for t in tasks_raw:
                    if isinstance(t, dict):
                        title = t.get("title", "任务")
                        ps = t.get("planned_start", "")
                        pe = t.get("planned_end", "")
                        pri = t.get("priority", 3)
                    else:
                        title = getattr(t, "title", "任务")
                        ps = str(getattr(t, "planned_start", ""))
                        pe = str(getattr(t, "planned_end", ""))
                        pri = getattr(t, "priority", 3)
                    events.append({"event": "task_created", "data": {"task": {"title": title, "planned_start": ps, "planned_end": pe, "priority": pri}}})
                mentor = next((getattr(l, "output", {}).get("mentor_msg") for l in logs if getattr(l, "agent_name", "") == "mentor" and isinstance(getattr(l, "output", None), dict)), "")
                if mentor:
                    events.append({"event": "mentor_msg", "data": {"text": mentor}})
                events.append({"event": "done", "data": {"trace_id": trace_id, "count": len([e for e in events if e.get("event") == "task_created"]), "source": "db_recover"}})
            self[trace_id] = events
            return events
        except Exception:
            logger.warning("plan_store.get_or_reconstruct failed: trace_id=%s", trace_id, exc_info=True)
            return None


plan_store: PlanStore = PlanStore()  # type: ignore

SYSTEM_PROMPT = """你是专业学习规划师。输入包含 goal{title,deadline,description} 与 preferences{hours_per_day}，请按以下规则生成循序渐进的学习计划，严格输出 JSON 数组，不要任何解释、Markdown 或前后缀：

输出格式（严格 JSON 数组）：
[
  {
    "title": "任务标题（具体可执行）",
    "planned_start": "YYYY-MM-DDTHH:MM:SS+00:00",
    "planned_end": "YYYY-MM-DDTHH:MM:SS+00:00",
    "priority": 1-5,
    "description": "任务详细说明，含目标与产出",
    "estimated_hours": 1.0
  }
]

约束：
- 每个任务必须包含 title/planned_start/planned_end/priority(1-5)/description/estimated_hours，estimated_hours 与 planned_start/planned_end 时长一致（1位小数）
- 任务时间不能重叠，每个任务 planned_start < planned_end 且互不交叉
- 每天总时长不超过 preferences.hours_per_day，按天均匀分配，循序渐进由易到难
- priority 1-5 区分优先级，循序渐进合理分布
- 按 goal.deadline 倒排，控制在截止前完成
- 只输出 JSON 数组。
"""

def mock_generate(goal: dict, preferences: dict, trace_id: str) -> tuple[list[dict], str, dict]:
    try:
        hours = int((preferences or {}).get("hours_per_day", 2))
    except (TypeError, ValueError):
        hours = 2
    hours = max(hours, 1)
    hours = min(hours, 8)
    # 计算天数：deadline 距今，取 min(7, 剩余天数)
    try:
        dl = goal["deadline"]
        if isinstance(dl, str):
            dl = datetime.fromisoformat(dl)
        if dl.tzinfo is None:
            dl = dl.replace(tzinfo=UTC)
    except Exception:
        dl = datetime.now(UTC) + timedelta(days=7)
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    # 支持更长排期：最长14天（用户要求“排的长一些”），仍受deadline约束
    days = max(1, min(14, (dl - today).days))
    tasks = []
    base_hour = 9
    for i in range(days):
        d = today + timedelta(days=i+1)
        # 支持更长排期：每天1-2任务，单任务时长 = hours/count，保证总时长≈hours
        count = 1 if hours <= 3 else 2
        per = round(hours / count, 1)
        # 若 per>4 则仍生成，但Critic会提示超载（用于演示长任务）
        for j in range(count):
            start = d.replace(hour=base_hour + j*5, minute=0)
            end = start + timedelta(hours=per)
            # 标题结合goal title
            title = f"{goal.get('title','学习')} - 任务 {i+1}-{j+1}"
            if j == 0 and goal.get("description"):
                title = f"{goal['title']}：学习阶段 {i+1}"
            tasks.append({
                "title": title,
                "planned_start": start.isoformat(),
                "planned_end": end.isoformat(),
                "priority": 4 if j==0 else 3,
                "date": d.date().isoformat(),
                "description": f"{goal.get('title','学习')} 第{i+1}阶段任务{j+1}：循序渐进完成",
                "estimated_hours": per,
            })
    mentor = f"已为「{goal.get('title')}」生成{len(tasks)}个任务，每天{hours}h，坚持即胜利！"
    return tasks, mentor, {}

async def llm_generate(goal: dict, preferences: dict) -> tuple[list[dict], str, dict]:
    # pytest/CI 快速短路：直接 mock，避免 15s 真实网络（对标 Pi faux provider）
    if os.getenv("PYTEST_CURRENT_TEST"):
        raise RuntimeError("no key - pytest")
    # Pi 风格 fallback：若全局 key 为空但存在 provider 专属 env key 仍可尝试（对标 Pi/packages/ai/src/models.ts:448-483 credential 解析）
    has_key = bool(settings.llm_api_key) or any(
        os.getenv(k)
        for k in ["ZHIPU_API_KEY", "BIGMODEL_API_KEY", "DEEPSEEK_API_KEY", "QWEN_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    )
    if not has_key:
        raise RuntimeError("no key")
    last_err: Exception | None = None
    for attempt in range(2):  # retry 1 次（共2次尝试）- JSON 解析重试，LLM 层已含 fallback+重试
        try:
            from app.core.llm import UnifiedClient

            client = UnifiedClient()
            user_msg = f"goal={json.dumps(goal, ensure_ascii=False)}\npreferences={json.dumps(preferences or {}, ensure_ascii=False)}\n截止:{goal.get('deadline')}"
            _msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}]
            # S2: 经 chat_with_meta 透出 finish_reason（兼容旧 FakeClient 仅有 chat）
            _meta: dict = {}
            try:
                _cm = getattr(client, "chat_with_meta", None)
                if callable(_cm):
                    _meta_res = await _cm(
                        _msgs,
                        model=settings.llm_model,
                        temperature=0.7,
                        timeout=15,
                        fallback=True,
                        max_retries=1,
                    )
                    if isinstance(_meta_res, dict):
                        _meta = dict(_meta_res)
                        text = str(_meta.get("text", "") or "")
                    else:
                        text = str(_meta_res or "")
                        _meta = {"text": text, "finish_reason": None}
                else:
                    text = await client.chat(
                        _msgs,
                        model=settings.llm_model,
                        temperature=0.7,
                        timeout=15,
                        fallback=True,
                        max_retries=1,
                    )
                    _meta = {"text": text, "finish_reason": None}
            except (AttributeError, TypeError):
                text = await client.chat(
                    _msgs,
                    model=settings.llm_model,
                    temperature=0.7,
                    timeout=15,
                    fallback=True,
                    max_retries=1,
                )
                _meta = {"text": text, "finish_reason": None}
            # S2: 记录本次 meta 供 graph planner_node 判断截断（保持 2 元返回兼容）
            try:
                global LAST_LLM_META
                LAST_LLM_META = dict(_meta) if isinstance(_meta, dict) else {"text": str(text or ""), "finish_reason": None}
                try:
                    llm_generate.last_meta = dict(LAST_LLM_META)  # type: ignore[attr-defined]
                except Exception:
                    pass
            except Exception:
                pass
            # 提取 JSON 数组
            start = text.find("[")
            end = text.rfind("]")+1
            if start>=0 and end>start:
                try:
                    arr = json.loads(text[start:end])
                except json.JSONDecodeError as je:
                    last_err = je
                    if attempt == 0:
                        continue
                    raise
                tasks = []
                for it in arr:
                    # 优先新格式 planned_start/planned_end，否则兼容旧 date/hours
                    ps = it.get("planned_start")
                    pe = it.get("planned_end")
                    if ps and pe:
                        try:
                            s = datetime.fromisoformat(ps)
                            e = datetime.fromisoformat(pe)
                            if s.tzinfo is None:
                                s = s.replace(tzinfo=UTC)
                            if e.tzinfo is None:
                                e = e.replace(tzinfo=UTC)
                            # 校验不重叠在上层保证，此处仅解析
                            est = float(it.get("estimated_hours", (e - s).total_seconds() / 3600))
                            desc = it.get("description", "")
                        except Exception:
                            continue
                    else:
                        date = it.get("date")
                        try:
                            d = datetime.fromisoformat(date)
                            if d.tzinfo is None: d = d.replace(tzinfo=UTC)
                        except Exception:
                            d = datetime.now(UTC) + timedelta(days=1)
                        # 用 date + 默认 9点
                        s = d.replace(hour=9, minute=0, second=0, microsecond=0)
                        hours = float(it.get("hours", it.get("estimated_hours", 1)))
                        e = s + timedelta(hours=hours)
                        est = hours
                        desc = it.get("description", "")
                        ps = s.isoformat()
                        pe = e.isoformat()
                    tasks.append({
                        "title": it.get("title","学习任务"),
                        "planned_start": s.isoformat() if isinstance(s, datetime) else ps,
                        "planned_end": e.isoformat() if isinstance(e, datetime) else pe,
                        "priority": max(1, min(5, int(it.get("priority",3)))),
                        "date": s.date().isoformat() if isinstance(s, datetime) else s[:10],
                        "description": desc or f"{it.get('title','学习任务')} 循序渐进完成",
                        "estimated_hours": round(est, 1),
                    })
                if tasks:
                    _ret_meta = dict(_meta) if isinstance(_meta, dict) else {"text": str(text or ""), "finish_reason": None}
                    return tasks, f"AI已为「{goal.get('title')}」定制{len(tasks)}个任务！", _ret_meta
            raise RuntimeError("parse empty")
        except Exception as e:
            last_err = e
            if attempt == 0 and isinstance(e, (json.JSONDecodeError, RuntimeError)):
                # JSON 解析失败重试 1 次
                continue
            raise
    if last_err:
        raise last_err
    raise RuntimeError("llm_generate failed after retry")

async def generate_plan(goal: dict, preferences: dict, trace_id: str) -> tuple[list[dict], str, str]:
    """返回 tasks, mentor_msg, source (mock|llm)"""
    # thinking trace 步骤记录
    thoughts: list[str] = []
    thoughts.append(f"思考1: 解析目标「{goal.get('title')}」截止 {goal.get('deadline')} 与偏好 {preferences}")
    hours = (preferences or {}).get("hours_per_day", 2)
    thoughts.append(f"思考2: 评估每日可用时长 {hours}h，计算剩余天数并按天分配，避免重叠与超载")
    thoughts.append("思考3: 拆解为循序渐进的子任务，确保每天总时长≤hours_per_day 且时间不重叠")
    # 先尝试 llm，失败降级 mock（3 元返回 tasks, mentor, meta；兼容旧 2 元 faux）
    try:
        thoughts.append("思考4: 调用 LLM 生成严格 JSON 任务列表（带 retry）")
        _llm_out = await llm_generate(goal, preferences)
        try:
            if isinstance(_llm_out, (list, tuple)) and len(_llm_out) == 3:
                tasks, mentor, _ = _llm_out  # type: ignore[misc]
            elif isinstance(_llm_out, (list, tuple)) and len(_llm_out) == 2:
                tasks, mentor = _llm_out  # type: ignore[misc]
            else:
                raise RuntimeError("parse empty")
        except ValueError:
            raise RuntimeError("parse empty")
        source = "llm"
        thoughts.append(f"思考5: LLM 成功生成 {len(tasks)} 个任务，校验优先级与时长")
    except Exception as e:
        thoughts.append(f"思考4: LLM 调用失败({e})，降级 mock_generate 兜底")
        _mock_out = mock_generate(goal, preferences, trace_id)
        try:
            if isinstance(_mock_out, (list, tuple)) and len(_mock_out) == 3:
                tasks, mentor, _ = _mock_out  # type: ignore[misc]
            else:
                tasks, mentor = _mock_out  # type: ignore[misc]
        except ValueError:
            tasks, mentor = [], ""
        source = "mock"
        thoughts.append(f"思考5: Mock 生成 {len(tasks)} 个任务，完成兜底排期")
    # 写入 plan_store 供 SSE 重放
    events = []
    for idx, th in enumerate(thoughts, 1):
        events.append({"event":"thought","data":{"agent":"planner","step": idx,"text": th}})
    events.append({"event":"tool_call","data":{"tool":"mock_generate" if source=="mock" else "llm_generate","args":{"goal_id":goal.get("id") if isinstance(goal, dict) else None,"days":len({t.get('date', '') for t in tasks if isinstance(t, dict)})}}})
    for t in tasks:
        if not isinstance(t, dict):
            continue
        events.append({"event":"task_created","data":{"task":{"title":t.get("title", "任务"),"planned_start":t.get("planned_start", ""),"planned_end":t.get("planned_end", ""),"priority":t.get("priority", 3),"description":t.get("description",""),"estimated_hours":t.get("estimated_hours")}}})
    events.append({"event":"done","data":{"trace_id":trace_id,"count":len(tasks),"source":source,"approved": True}})
    plan_store.put(trace_id, events)
    return tasks, mentor, source
