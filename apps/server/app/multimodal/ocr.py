import base64

async def qwen_ocr(image_bytes: bytes) -> dict:
    # 若有Key则调Qwen-VL，否则mock课表
    from app.core.config import get_settings
    s = get_settings()
    if not s.llm_api_key:
        # mock: 返回2门课
        return {
            "courses": [
                {"course": "高等数学", "time": "周一 08:00-10:00", "confidence": 0.92},
                {"course": "数据结构", "time": "周三 14:00-16:00", "confidence": 0.88},
            ],
            "text": "mock OCR: 高等数学 周一 08:00",
            "confidence": 0.9,
        }
    try:
        from openai import AsyncOpenAI
        # Qwen-VL 兼容 OpenAI 视觉接口
        client = AsyncOpenAI(api_key=s.llm_api_key, base_url=s.llm_base_url)
        b64 = base64.b64encode(image_bytes).decode()
        resp = await client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "识别课表，输出JSON {courses:[{course,time,confidence}], text}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}],
            timeout=15,
        )
        import json
        txt = resp.choices[0].message.content or ""
        # 尝试解析
        start = txt.find("{"); end = txt.rfind("}")+1
        if start>=0 and end>start:
            return json.loads(txt[start:end])
    except Exception:
        pass
    return {"courses": [], "text": "", "confidence": 0.5}
