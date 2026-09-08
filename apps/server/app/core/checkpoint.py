"""细致收口：SqliteSaver 文件持久化（P0-3）

MemorySaver 重启丢，PlanStore 已 DB 回退，但 LangGraph checkpoint 仍内存。
本模块提供 FileMemorySaver：继承 MemorySaver，额外 pickle 到 data/checkpoints.db，
实现 BaseCheckpointSaver 最小接口，支持 get/put/list，无需 langgraph-checkpoint-sqlite 依赖。
"""
import pickle
import sqlite3
from pathlib import Path

try:
    from langgraph.checkpoint.memory import MemorySaver
    _has_base = True
except Exception:
    MemorySaver = object  # type: ignore
    _has_base = False

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "checkpoints.db"

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
                cur = conn.execute("SELECT thread_id, data FROM checkpoints LIMIT 1")
                row = cur.fetchone()
                if not row:
                    return
                # 兼容旧单 thread 模式：尝试加载全量
                try:
                    # 新格式：{"storage":..., "writes":..., "blobs":...}
                    blob = row[1]
                    data = pickle.loads(blob)
                    if isinstance(data, dict) and "storage" in data:
                        # 全量恢复
                        for tid, ns_dict in data.get("storage", {}).items():
                            self.storage[tid] = ns_dict  # type: ignore
                        for k, v in data.get("writes", {}).items():
                            self.writes[k] = v  # type: ignore
                        for k, v in data.get("blobs", {}).items():
                            self.blobs[k] = v  # type: ignore
                        return
                except Exception:
                    pass
                # 旧格式：逐 thread
                cur2 = conn.execute("SELECT thread_id, data FROM checkpoints")
                for tid, blob in cur2.fetchall():
                    try:
                        data = pickle.loads(blob)
                        if hasattr(self, "storage"):
                            self.storage[tid] = data  # type: ignore
                    except Exception:
                        continue
            finally:
                conn.close()
        except Exception:
            pass

    def _persist(self, thread_id: str | None = None):
        if not _has_base:
            return
        try:
            # 全量持久化 storage+writes+blobs（保证重启可恢复完整链）
            payload = {
                "storage": {k: dict(v) for k, v in getattr(self, "storage", {}).items()} if hasattr(self, "storage") else {},
                "writes": dict(getattr(self, "writes", {})),
                "blobs": dict(getattr(self, "blobs", {})),
            }
            blob = pickle.dumps(payload)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=5.0)
            try:
                # 单键全量，thread_id 固定为 _all
                conn.execute("INSERT OR REPLACE INTO checkpoints (thread_id, data) VALUES (?, ?)", ("_all", blob))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    # 覆盖 put / aget 等，若 MemorySaver 已实现 aput，则同时持久化
    def put(self, config, checkpoint, metadata, new_versions=None):  # type: ignore
        res = super().put(config, checkpoint, metadata, new_versions) if _has_base else None  # type: ignore
        try:
            tid = (config.get("configurable") or {}).get("thread_id") if isinstance(config, dict) else None
            if tid:
                self._persist(tid)
        except Exception:
            pass
        return res

    async def aput(self, config, checkpoint, metadata, new_versions=None):  # type: ignore
        res = await super().aput(config, checkpoint, metadata, new_versions) if _has_base and hasattr(super(), "aput") else self.put(config, checkpoint, metadata, new_versions)  # type: ignore
        try:
            tid = (config.get("configurable") or {}).get("thread_id") if isinstance(config, dict) else None
            if tid:
                self._persist(tid)
        except Exception:
            pass
        return res
