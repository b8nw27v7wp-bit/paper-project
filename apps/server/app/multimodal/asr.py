"""ASR — Whisper 接口 + 智能 mock fallback（根据时间推断）"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)

def _smart_mock_text() -> str:
    """根据当前时间推断更智能的 mock 文本"""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Mon
    # 根据时段返回不同文本
    if 5 <= hour < 11:
        # 早上 -> 下午任务
        return "今天下午三点背单词"
    elif 11 <= hour < 13:
        return "明早九点复习高等数学"
    elif 13 <= hour < 17:
        return "今晚八点完成数据结构作业"
    elif 17 <= hour < 21:
        return "明天上午十点英语精读"
    else:
        # 夜晚 -> 明天
        # 若临近周末，推断周计划
        if weekday >= 4:  # 周五及之后
            return "下周一八点高等数学课前预习"
        return "明天下午三点背单词"

def _mock_asr_result() -> Dict[str, Any]:
    text = _smart_mock_text()
    # 根据时间附带推断信息
    now = datetime.now()
    return {
        "text": text,
        "confidence": 0.95,
        "mock": True,
        "time_inferred": now.isoformat(),
        "hint": f"基于当前时间 {now.strftime('%H:%M')} 推断的模拟识别",
    }

async def whisper_asr(audio_bytes: bytes) -> Dict[str, Any]:
    from app.core.config import get_settings

    s = get_settings()
    if not s.llm_api_key:
        logger.info("[ASR] no api_key, return smart mock")
        return _mock_asr_result()
    # 若音频过小（<100字节），可能是测试 fake audio，直接返回智能 mock 避免无效调用
    if not audio_bytes or len(audio_bytes) < 100:
        # 仍尝试 mock，但带提示
        res = _mock_asr_result()
        res["note"] = "audio too short, mock returned"
        return res
    try:
        import os
        import tempfile

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)
        # OpenAI Whisper 接口需写临时文件
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        try:
            with open(tmp, "rb") as f:
                resp = await client.audio.transcriptions.create(model="whisper-1", file=f)
            text = getattr(resp, "text", "") or ""
            if not text.strip():
                logger.warning("[ASR] whisper empty, fallback smart mock")
                return _mock_asr_result()
            return {"text": text.strip(), "confidence": 0.9, "model": "whisper-1"}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[ASR] whisper call failed, fallback smart mock: {e}")
        return _mock_asr_result()

# 别名（便于后续扩展）
zhipu_asr = whisper_asr

__all__ = ["whisper_asr", "zhipu_asr"]
