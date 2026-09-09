"""S9 FauxProvider：queue 响应编排（Pi faux 启示），仅供新测试用。

每个响应含 text/finish_reason/usage/cost；按序弹出，空则复最后一条。
promptCache 风格 kw 直接忽略（治療不用）。
llm.py PYTEST_CURRENT_TEST 分支保留不动，faux 不替代该短路。
"""
from typing import Any


class FauxProvider:
    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self._queue: list[dict[str, Any]] = []
        for r in responses or []:
            if isinstance(r, dict):
                self._queue.append(
                    {
                        "text": str(r.get("text", "") or ""),
                        "finish_reason": r.get("finish_reason", "stop"),
                        "usage": r.get("usage"),
                        "cost": r.get("cost", 0.0),
                    }
                )
            else:
                self._queue.append({"text": str(r), "finish_reason": "stop", "usage": None, "cost": 0.0})
        if not self._queue:
            self._queue.append({"text": "", "finish_reason": "stop", "usage": None, "cost": 0.0})
        self._last: dict[str, Any] = dict(self._queue[-1])

    async def chat(self, messages: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
        # promptCache 风格参数直接忽略
        _ = messages
        _ = kw
        if self._queue:
            res = self._queue.pop(0)
            self._last = dict(res)
            return dict(res)
        return dict(self._last)

    async def chat_with_meta(self, messages: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
        return await self.chat(messages, **kw)

    async def chat_text(self, messages: list[dict[str, Any]] | None = None, **kw: Any) -> str:
        res = await self.chat(messages, **kw)
        return str(res.get("text", "") or "")
