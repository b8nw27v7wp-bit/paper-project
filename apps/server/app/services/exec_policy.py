"""Wave A 执行策略纯函数模块（Codex 对标 protocol.rs:984 四档 + execpolicy decision 三值）。

- Decision 三值：Allow / Prompt / Forbidden（str Enum，值保持首字母大写便于与 Codex 对齐）。
- _PREFIX_RULES：pattern→(Decision, justification)，前缀匹配取最长（max）。
  初始含：calendar 写/Prompt、todo 写/Allow、tasks 批量>50/Forbidden。
- check(action:str) -> (Decision, justification)：前缀匹配 max()，无规则启发回退
  （写操作 Prompt、读 Allow、删/批量 Forbidden）。
- never 下 Prompt 自动降 Forbidden 由调用方（plans.py 网关）处理，本模块不隐式降级。
- 规则追加 add_rule() 仅改内存；持久化（Redis/DB）下轮再做，此处只留注释说明。

纯函数：除 add_rule 对 _PREFIX_RULES 的内存写入外无副作用，不读 Redis/DB/网络。
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum

logger = logging.getLogger("app.exec_policy")

_APPROVAL_RULES_KEY = "approval_rules"


class Decision(str, Enum):
    Allow = "Allow"
    Prompt = "Prompt"
    Forbidden = "Forbidden"


# pattern -> (Decision, justification)
# 说明：tasks.batch 条目语义为“批量>50 禁止”；check() 内对该前缀做计数解析，
# 小批量（<=50）放行 Allow，大批量（>50）或无计数时按 Forbidden 处理（保守默认）。
_PREFIX_RULES: dict[str, tuple[Decision, str]] = {
    "calendar": (Decision.Prompt, "calendar写操作需人工确认"),
    "todo.write": (Decision.Allow, "todo写操作低风险直行"),
    "tasks.batch": (Decision.Forbidden, "tasks批量写(>50)禁止直行"),
}

_WRITE_HINTS = ("write", "create", "update", "edit", "set", "add", "sync", "calendar", "mint", "approve")
_DELETE_HINTS = ("delete", "remove", "drop", "destroy", "erase", "rm ")
_BATCH_HINTS = ("batch", "bulk")

_COUNT_RE = re.compile(r"(\d+)")


def _extract_count(action: str) -> int | None:
    try:
        m = _COUNT_RE.search(action or "")
        if not m:
            return None
        return int(m.group(1))
    except Exception:
        return None


def _normalize_decision(decision: Decision | str) -> Decision:
    if isinstance(decision, Decision):
        return decision
    try:
        v = str(decision or "").strip().lower()
    except Exception:
        raise ValueError(f"invalid decision: {decision!r}")
    if v == "allow":
        return Decision.Allow
    if v == "prompt":
        return Decision.Prompt
    if v in ("forbidden", "deny", "reject", "blocked"):
        return Decision.Forbidden
    # 兼容首字母大写直传
    try:
        return Decision(str(decision).strip())
    except Exception:
        raise ValueError(f"invalid decision: {decision!r}")


def check(action: str) -> tuple[Decision, str]:
    """前缀匹配 max()，无规则启发回退。

    - 归一化：strip；空串按 Allow（无操作直行）。
    - 前缀命中：action == pattern 或 action.startswith(pattern) 中取最长 pattern。
      tasks.batch 前缀命中时若能解析出计数且 <=50 则 Allow（小批量放行），否则 Forbidden。
    - 未命中：启发回退——含删/批量关键字 Forbidden；含写关键字 Prompt；其余读 Allow。
    """
    try:
        act = str(action or "").strip()
    except Exception:
        act = ""
    if not act:
        return Decision.Allow, "empty action defaults allow"
    # 前缀匹配 max()
    best: str | None = None
    try:
        for pat in _PREFIX_RULES.keys():
            try:
                if act == pat or act.startswith(pat):
                    if best is None or len(pat) > len(best):
                        best = pat
            except Exception:
                continue
    except Exception:
        best = None
    if best is not None:
        try:
            dec, just = _PREFIX_RULES[best]
        except Exception:
            dec, just = Decision.Prompt, "rule match"
        # tasks 批量>50 语义：小批量放行
        try:
            if best == "tasks.batch":
                cnt = _extract_count(act)
                if cnt is not None and cnt <= 50:
                    return Decision.Allow, f"tasks小批量({cnt}<=50)允许直行"
                # 无计数或>50：沿用规则（Forbidden）
                return dec, just
        except Exception:
            pass
        return dec, just
    # 启发回退
    try:
        low = act.lower()
    except Exception:
        low = ""
    try:
        if any(k in low for k in _DELETE_HINTS):
            return Decision.Forbidden, "heuristic: delete-like forbidden"
        if any(k in low for k in _BATCH_HINTS):
            cnt = _extract_count(act)
            # 批量默认 Forbidden；小批量(<=50)且非删除类时放行 Allow，保持与 tasks.batch 一致
            if cnt is not None and cnt <= 50 and not any(k in low for k in _DELETE_HINTS):
                # 批量小但含写语义时仍 Prompt？此处保守 Allow，由调用方按需收紧
                return Decision.Allow, f"heuristic: small batch({cnt}<=50) allow"
            return Decision.Forbidden, "heuristic: batch/bulk forbidden"
        if any(k in low for k in _WRITE_HINTS):
            return Decision.Prompt, "heuristic: write-like needs prompt"
    except Exception:
        pass
    return Decision.Allow, "heuristic: read-like allow"


def add_rule(prefix: str, decision: Decision | str, justification: str | None = None) -> tuple[Decision, str]:
    """规则追加（内存，幂等）。

    - 同 prefix+同 decision 重复调用返回相同结果，无副作用差异（幂等）。
    - 同 prefix 不同 decision 则覆盖为新值（后写胜出）。
    - justification 为空时沿用旧值或自动生成 `"rule:{prefix}->{decision}"`。
    - 持久化说明：本轮仅内存 dict；下轮持久化拟走 Redis `exec:rules:*` + DB 表（待定），
      重启后需重放，此处不做 IO 保持纯函数模块可测性。
    """
    try:
        p = str(prefix or "").strip()
    except Exception:
        p = ""
    if not p:
        raise ValueError("prefix 不能为空")
    dec = _normalize_decision(decision)
    try:
        just = str(justification).strip() if justification is not None else ""
    except Exception:
        just = ""
    if not just:
        try:
            old = _PREFIX_RULES.get(p)
            if old is not None and old[0] == dec and old[1]:
                just = old[1]
            else:
                just = f"rule:{p}->{dec.value}"
        except Exception:
            just = f"rule:{p}->{dec.value}"
    _PREFIX_RULES[p] = (dec, just)
    return dec, just


def list_rules() -> dict[str, dict[str, str]]:
    """当前规则快照（供 approve-rule 接口回显与测试断言）。"""
    out: dict[str, dict[str, str]] = {}
    try:
        for k, (d, j) in list(_PREFIX_RULES.items()):
            try:
                out[str(k)] = {"decision": d.value if isinstance(d, Decision) else str(d), "justification": str(j)}
            except Exception:
                continue
    except Exception:
        pass
    return out


def remove_rule(prefix: str) -> bool:
    """规则删除（内存，幂等）。

    - 存在则删除返回 True；不存在返回 False（调用方 200 幂等）。
    - prefix 为空抛 ValueError（调用方转 40001）。
    """
    try:
        p = str(prefix or "").strip()
    except Exception:
        p = ""
    if not p:
        raise ValueError("prefix 不能为空")
    try:
        return _PREFIX_RULES.pop(p, None) is not None
    except Exception:
        return False


def _snapshot_payload() -> list[dict]:
    """内存全量快照 → DB 行 payload（list[{prefix,decision,justification}]，按 prefix 排序保证确定性）。"""
    items: list[dict] = []
    try:
        for k in sorted(_PREFIX_RULES.keys()):
            try:
                d, j = _PREFIX_RULES[k]
                items.append(
                    {
                        "prefix": str(k),
                        "decision": d.value if isinstance(d, Decision) else str(d),
                        "justification": str(j),
                    }
                )
            except Exception:
                continue
    except Exception:
        pass
    return items


def save_to_db(session) -> bool:
    """内存全量写回 global_state(key='approval_rules')，失败只 warn 不抛（内存为准）。

    注释：多实例后写胜出（last-write-wins），save 失败返回 False 且 rollback，调用方 list 不被旧 DB 覆盖。
    """
    try:
        if session is None:
            return False
        raw = json.dumps(_snapshot_payload(), ensure_ascii=False)
        from sqlalchemy import text

        from app.core.database import USE_PG

        session.execute(text("CREATE TABLE IF NOT EXISTS global_state (key TEXT PRIMARY KEY, value TEXT)"))
        if USE_PG:
            session.execute(
                text("INSERT INTO global_state (key, value) VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"),
                {"k": _APPROVAL_RULES_KEY, "v": raw},
            )
        else:
            session.execute(
                text("INSERT OR REPLACE INTO global_state (key, value) VALUES (:k, :v)"),
                {"k": _APPROVAL_RULES_KEY, "v": raw},
            )
        session.commit()
        return True
    except Exception as e:
        try:
            logger.warning("approval_rules persist failed: %s", e)
        except Exception:
            pass
        try:
            if session is not None and hasattr(session, "rollback"):
                session.rollback()
        except Exception:
            pass
        return False


def load_from_db(session) -> bool:
    """从 global_state(key='approval_rules') 重载全量进内存；缺表/无行则保持内存不变。失败只 warn 不抛。

    H2：仅当 DB 有有效非空行才合并；无行/空列表/解析失败一律保持内存不动（防旧 DB 覆盖内存新规则）。
    注释：多实例后写胜出（last-write-wins）。
    """
    try:
        if session is None:
            return False
        from sqlalchemy import text

        try:
            row = session.execute(text("SELECT value FROM global_state WHERE key=:k"), {"k": _APPROVAL_RULES_KEY}).first()
        except Exception as e:
            try:
                logger.warning("approval_rules load failed: %s", e)
            except Exception:
                pass
            try:
                if hasattr(session, "rollback"):
                    session.rollback()
            except Exception:
                pass
            return False
        if row is None:
            return False
        try:
            val = row[0]
        except Exception:
            val = row
        if not isinstance(val, str) or not val:
            return False
        try:
            data = json.loads(val)
        except Exception as e:
            try:
                logger.warning("approval_rules parse failed: %s", e)
            except Exception:
                pass
            return False
        if not isinstance(data, list):
            return False
        if len(data) == 0:
            # H2：DB 无有效行时保持内存不动（不清内存，避免覆盖内存新规则）。
            return False
        new_rules: dict[str, tuple[Decision, str]] = {}
        for item in data:
            try:
                if not isinstance(item, dict):
                    continue
                p = str(item.get("prefix") or "").strip()
                if not p:
                    continue
                dec = _normalize_decision(item.get("decision"))
                try:
                    just = str(item.get("justification") or "").strip()
                except Exception:
                    just = ""
                if not just:
                    just = f"rule:{p}->{dec.value}"
                new_rules[p] = (dec, just)
            except Exception:
                continue
        if not new_rules:
            return False
        _PREFIX_RULES.clear()
        _PREFIX_RULES.update(new_rules)
        return True
    except Exception as e:
        try:
            logger.warning("approval_rules load failed: %s", e)
        except Exception:
            pass
        return False
