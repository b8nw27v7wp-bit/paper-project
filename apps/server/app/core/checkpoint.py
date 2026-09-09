"""细致收口：SqliteSaver 文件持久化（P0-3）

MemorySaver 重启丢，PlanStore 已 DB 回退，但 LangGraph checkpoint 仍内存。
本模块提供 FileMemorySaver：继承 MemorySaver，额外 pickle 到 data/checkpoints.db，
实现 BaseCheckpointSaver 最小接口，支持 get/put/list，无需 langgraph-checkpoint-sqlite 依赖。

持久格式（v2，按 thread 分片）：
- 每 thread 一行 ``(thread_id, pickle({"storage": {tid: ...}, "writes": {...}, "blobs": {...}}))``，
  每次 put 仅重写本 thread 分片（O(单trace)而非 O(全库)，根治 134MB 全量重写致每节点 7s）。
- 兼容读旧 ``_all`` 单键全量：首次初始化时迁移为分片行后删除 ``_all``。
- 上限：单分片超 ``_MAX_THREAD_BYTES`` 跳过落盘（仅内存）；总行数超 ``_MAX_THREADS`` 按 updated_at 淘汰最旧。
"""
import logging
import pickle
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from langgraph.checkpoint.memory import MemorySaver
    _has_base = True
except Exception:
    MemorySaver = object  # type: ignore
    _has_base = False

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "checkpoints.db"

# 单 thread 分片上限 1MB，总 thread 上限 200（超限跳过/淘汰，内存态不受影响）
_MAX_THREAD_BYTES = 1024 * 1024
_MAX_THREADS = 200


def _tid_of(config: Any) -> str | None:
    try:
        if isinstance(config, dict):
            c = config.get("configurable") or {}
            tid = c.get("thread_id")
            return str(tid) if tid is not None else None
    except Exception:
        pass
    return None


def _thread_slice(storage: Any, writes: Any, blobs: Any, tid: str) -> dict:
    """抽取单 thread 分片（纯数据拷贝，不碰原结构）。"""
    try:
        ns_dict = storage.get(tid, {}) if hasattr(storage, "get") else {}
        store_part = {tid: dict(ns_dict)} if isinstance(ns_dict, dict) else {tid: {}}
    except Exception:
        store_part = {tid: {}}

    def _owned(mapping: Any) -> dict:
        out: dict = {}
        try:
            items = mapping.items() if hasattr(mapping, "items") else []
            for k, v in items:
                try:
                    if isinstance(k, tuple) and k and k[0] == tid:
                        out[k] = v
                    elif not isinstance(k, tuple) and k == tid:
                        out[k] = v
                except Exception:
                    continue
        except Exception:
            pass
        return out

    try:
        writes_part = _owned(writes)
    except Exception:
        writes_part = {}
    try:
        blobs_part = _owned(blobs)
    except Exception:
        blobs_part = {}
    return {"storage": store_part, "writes": writes_part, "blobs": blobs_part}


def _restore_slice(target_storage: Any, target_writes: Any, target_blobs: Any, payload: dict) -> None:
    """分片 payload 合并进内存结构（storage 重建 defaultdict，防新 ns put KeyError）。"""
    try:
        for tid, ns_dict in (payload.get("storage") or {}).items():
            restored = defaultdict(dict)
            if isinstance(ns_dict, dict):
                for ns, ckpts in ns_dict.items():
                    restored[ns] = dict(ckpts) if isinstance(ckpts, dict) else ckpts
            target_storage[tid] = restored
    except Exception:
        logger.warning("checkpoint slice storage restore failed", exc_info=True)
    try:
        for k, v in (payload.get("writes") or {}).items():
            target_writes[k] = v
    except Exception:
        logger.warning("checkpoint slice writes restore failed", exc_info=True)
    try:
        for k, v in (payload.get("blobs") or {}).items():
            target_blobs[k] = v
    except Exception:
        logger.warning("checkpoint slice blobs restore failed", exc_info=True)


class FileMemorySaver(MemorySaver if _has_base else object):  # type: ignore
    """内存 + 文件双写，重启可恢复（WAL + busy_timeout 复用）"""
    def __init__(self, db_path: Path | None = None):
        if _has_base:
            super().__init__()  # type: ignore
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._load_from_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _load_from_db(self):
        if not _has_base:
            return
        try:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
            try:
                rows = conn.execute("SELECT thread_id, data FROM checkpoints").fetchall()
            finally:
                conn.close()
        except Exception:
            return
        migrated = False
        for tid, blob in rows:
            try:
                data = pickle.loads(blob)
            except Exception:
                continue
            if tid == "_all":
                # 旧格式单键全量： explode 为分片（超限分片丢弃），随后删除 _all
                if isinstance(data, dict) and "storage" in data:
                    try:
                        for t, ns_dict in (data.get("storage") or {}).items():
                            part = {"storage": {t: ns_dict}, "writes": {}, "blobs": {}}
                            try:
                                for k, v in (data.get("writes") or {}).items():
                                    if isinstance(k, tuple) and k and k[0] == t:
                                        part["writes"][k] = v
                            except Exception:
                                pass
                            try:
                                for k, v in (data.get("blobs") or {}).items():
                                    if isinstance(k, tuple) and k and k[0] == t:
                                        part["blobs"][k] = v
                            except Exception:
                                pass
                            try:
                                raw = pickle.dumps(part)
                            except Exception:
                                continue
                            _restore_slice(self.storage, self.writes, self.blobs, part)
                            if len(raw) > _MAX_THREAD_BYTES:
                                logger.warning("checkpoint migrate skip oversize thread: tid=%s size=%d", t, len(raw))
                                continue
                            self._write_row(t, raw)
                        migrated = True
                    except Exception:
                        logger.warning("checkpoint _all migration failed", exc_info=True)
                continue
            if not isinstance(data, dict) or "storage" not in data:
                continue
            _restore_slice(self.storage, self.writes, self.blobs, data)
        if migrated:
            try:
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
                try:
                    conn.execute("DELETE FROM checkpoints WHERE thread_id='_all'")
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                pass

    def _write_row(self, tid: str, blob: bytes) -> None:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
        try:
            conn.execute("INSERT OR REPLACE INTO checkpoints (thread_id, data) VALUES (?, ?)", (tid, blob))
            conn.execute(
                "DELETE FROM checkpoints WHERE thread_id NOT IN "
                "(SELECT thread_id FROM checkpoints ORDER BY updated_at DESC LIMIT ?)",
                (_MAX_THREADS,),
            )
            conn.commit()
        finally:
            conn.close()

    def _persist(self, thread_id: str | None = None):
        if not _has_base:
            return
        if not thread_id:
            return
        try:
            payload = _thread_slice(
                getattr(self, "storage", {}), getattr(self, "writes", {}), getattr(self, "blobs", {}), thread_id
            )
            try:
                blob = pickle.dumps(payload)
            except Exception:
                logger.warning("checkpoint slice dumps failed: tid=%s", thread_id, exc_info=True)
                return
            if len(blob) > _MAX_THREAD_BYTES:
                logger.warning("checkpoint slice too large, skip file persist: tid=%s size=%d", thread_id, len(blob))
                return
            self._write_row(thread_id, blob)
        except Exception:
            logger.warning("checkpoint persist failed: tid=%s", thread_id, exc_info=True)

    # 覆盖 put / aput 等，若 MemorySaver 已实现 aput，则同时持久化
    def put(self, config, checkpoint, metadata, new_versions=None):  # type: ignore
        res = super().put(config, checkpoint, metadata, new_versions) if _has_base else None  # type: ignore
        try:
            self._persist(_tid_of(config))
        except Exception:
            pass
        return res

    async def aput(self, config, checkpoint, metadata, new_versions=None):  # type: ignore
        res = await super().aput(config, checkpoint, metadata, new_versions) if _has_base and hasattr(super(), "aput") else self.put(config, checkpoint, metadata, new_versions)  # type: ignore
        # 同步 put 内已 _persist（经 self.put 分支）；异步直调分支需补一次（按 tid，避免重复写时以 res 为准幂等）
        try:
            if _has_base and hasattr(super(), "aput"):
                self._persist(_tid_of(config))
        except Exception:
            pass
        return res

    def put_writes(self, config, writes, task_id, task_path=""):  # type: ignore
        res = super().put_writes(config, writes, task_id, task_path) if _has_base and hasattr(super(), "put_writes") else None  # type: ignore
        try:
            self._persist(_tid_of(config))
        except Exception:
            pass
        return res

    async def aput_writes(self, config, writes, task_id, task_path=""):  # type: ignore
        if _has_base and hasattr(super(), "aput_writes"):
            res = await super().aput_writes(config, writes, task_id, task_path)  # type: ignore
        else:
            res = self.put_writes(config, writes, task_id, task_path)
        try:
            if _has_base and hasattr(super(), "aput_writes"):
                self._persist(_tid_of(config))
        except Exception:
            pass
        return res
