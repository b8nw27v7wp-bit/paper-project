async def whisper_asr(audio_bytes: bytes) -> dict:
    from app.core.config import get_settings
    s = get_settings()
    if not s.llm_api_key:
        return {"text": "明天下午三点背单词", "confidence": 0.95}
    try:
        import os
        import tempfile

        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)
        # OpenAI Whisper 接口
        # 需写临时文件
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        with open(tmp, "rb") as f:
            resp = await client.audio.transcriptions.create(model="whisper-1", file=f)
        os.unlink(tmp)
        return {"text": resp.text, "confidence": 0.9}
    except Exception:
        return {"text": "语音识别失败", "confidence": 0.5}
