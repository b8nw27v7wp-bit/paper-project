"""P2 桌面代理：窗口状态 / 通知代理（Electron ↔ FastAPI 双向同步）"""
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.core.deps import get_current_user_id

router = APIRouter()

# 内存窗口状态存储（用户级）+ 可选DB持久化占位
# W17-18: better-sqlite3 存窗口状态本地，云端仅作同步代理便于多端一致
_window_state_mem: dict[int, dict] = {}
_notify_log: list[dict] = []


class WindowState(BaseModel):
    x: int | None = None
    y: int | None = None
    width: int = Field(default=1280, ge=800, le=3840)
    height: int = Field(default=860, ge=600, le=2160)
    is_maximized: bool = False
    display_id: str | None = None


class NotifyPayload(BaseModel):
    title: str = Field(max_length=80)
    body: str = Field(max_length=400)
    tag: str | None = None  # 用于聚合未读
    silent: bool = False
    level: str = Field(default="info", pattern="^(info|warn|success)$")


@router.get("/desktop/window-state", summary="获取窗口状态（云端代理）")
def get_window_state(session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    state = _window_state_mem.get(user_id)
    if state:
        return {"code": 200, "msg": "ok", "data": {**state, "source": "mem"}}
    # M7: DB 回退
    try:
        from sqlalchemy import text
        import json

        row = session.exec(text("SELECT value FROM global_state WHERE key=:k"), {"k": f"window:{user_id}"}).first()  # type: ignore
        if row:
            val = row[0] if isinstance(row, (list, tuple)) else row
            data = json.loads(val) if isinstance(val, str) else val
            _window_state_mem[user_id] = data
            return {"code": 200, "msg": "ok", "data": {**data, "source": "db"}}
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": {"width": 1280, "height": 860, "is_maximized": False, "source": "default"}}


@router.put("/desktop/window-state", summary="上传/同步窗口状态（Electron 保存时调用）")
def put_window_state(payload: WindowState, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    data = payload.model_dump()
    data["updated_at"] = datetime.now(UTC).isoformat()
    data["user_id"] = user_id
    _window_state_mem[user_id] = data
    try:
        from sqlalchemy import text
        import json

        session.exec(text("CREATE TABLE IF NOT EXISTS global_state (key TEXT PRIMARY KEY, value TEXT)"))
        session.exec(text("INSERT OR REPLACE INTO global_state (key, value) VALUES (:k, :v)"), {"k": f"window:{user_id}", "v": json.dumps(data)})
        session.commit()
    except Exception:
        pass
    return {"code": 200, "msg": "ok", "data": data}


@router.post("/desktop/notify", summary="桌面通知代理（服务端推送 → Electron Tray/Notification）")
def post_notify(payload: NotifyPayload, user_id: int = Depends(get_current_user_id)):
    entry = payload.model_dump()
    entry.update({"user_id": user_id, "created_at": datetime.now(UTC).isoformat(), "id": len(_notify_log) + 1})
    _notify_log.append(entry)
    # 仅保留最近 50 条
    if len(_notify_log) > 50:
        del _notify_log[:-50]
    # 返回给 Electron 的 tray/tipc 消费（同时兼容旧前端 ok 字段）
    return {"code": 200, "msg": "ok", "data": {"delivered": True, "ok": True, "entry": entry, "unread": len([x for x in _notify_log if x["user_id"] == user_id])}}


@router.get("/desktop/notifications", summary="拉取通知历史（供大屏/托盘未读）")
def list_notifications(limit: int = 10, user_id: int = Depends(get_current_user_id)):
    items = [x for x in _notify_log if x["user_id"] == user_id][-limit:]
    return {"code": 200, "msg": "ok", "data": {"items": items, "unread": len(items)}}


@router.get("/desktop/config", summary="桌面端配置（sidecar 地址 + 功能开关）")
def get_desktop_config(user_id: int = Depends(get_current_user_id)):
    # 复用 FastAPI /api/v1 代理 http://localhost:5173 的同源配置
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "sidecar": {"host": "127.0.0.1", "port": 8000, "health": "/health"},
            "features": {"tray": True, "notification": True, "windowState": True, "autoLaunch": False},
            "user_id": user_id,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    }


@router.post("/desktop/sync", summary="一键同步：窗口+通知+版本")
def desktop_sync(payload: dict[str, Any] = {}, session: Session = Depends(get_session), user_id: int = Depends(get_current_user_id)):
    # 合并窗口与通知的批量同步（减少 Electron IPC 往返）— 兼容 bounds/window 双键名（M1）
    window_data = payload.get("window") or payload.get("bounds") or payload.get("windowState")
    if window_data:
        try:
            ws = WindowState(**window_data)
            data = {**ws.model_dump(), "updated_at": datetime.now(UTC).isoformat(), "user_id": user_id}
            _window_state_mem[user_id] = data
            # M7: 同步落库 global_state（内存+DB双写）
            try:
                from sqlalchemy import text

                session.exec(text("CREATE TABLE IF NOT EXISTS global_state (key TEXT PRIMARY KEY, value TEXT)"))
                import json

                session.exec(text("INSERT OR REPLACE INTO global_state (key, value) VALUES (:k, :v)"), {"k": f"window:{user_id}", "v": json.dumps(data)})
                session.commit()
            except Exception:
                pass
        except Exception:
            pass
    if "notify" in payload and isinstance(payload["notify"], dict):
        try:
            np = NotifyPayload(**payload["notify"])
            return post_notify(np, user_id)
        except Exception:
            pass
    return {"code": 200, "msg": "ok", "data": {"window": _window_state_mem.get(user_id), "notifications": len(_notify_log)}}
