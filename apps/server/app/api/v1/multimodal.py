from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.deps import get_current_user_id
from app.multimodal.asr import whisper_asr
from app.multimodal.ocr import qwen_ocr

router = APIRouter()

@router.post("/multimodal/ocr")
async def ocr(request: Request, file: UploadFile = File(...), user_id: int = Depends(get_current_user_id)):
    from app.core.ratelimit import check_rate_limit

    check_rate_limit(request, user_id)
    if file.size is not None and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "图片>10M"})
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "空文件"})
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "图片>10M"})
    # 仅允许图片 MIME（H-04）
    if file.content_type and not file.content_type.startswith("image/"):
        # 允许空 content_type，回退到后缀检查
        from pathlib import Path

        ext = Path(file.filename or "").suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "仅支持图片"})
    res = await qwen_ocr(data)
    return {"code": 200, "msg": "ok", "data": res}

@router.post("/multimodal/asr")
async def asr(request: Request, file: UploadFile = File(...), user_id: int = Depends(get_current_user_id)):
    from app.core.ratelimit import check_rate_limit

    check_rate_limit(request, user_id)
    if file.size is not None and file.size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "音频>5M"})
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "空文件"})
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"code": 40001, "msg": "音频>5M"})
    if file.content_type and not file.content_type.startswith("audio/"):
        from pathlib import Path

        ext = Path(file.filename or "").suffix.lower()
        if ext not in (".webm", ".mp3", ".wav", ".m4a", ".ogg"):
            raise HTTPException(status_code=400, detail={"code": 40001, "msg": "仅支持音频"})
    res = await whisper_asr(data)
    return {"code": 200, "msg": "ok", "data": res}


@router.get("/multimodal/capabilities")
async def capabilities():
    """返回支持的模态与模型信息（供前端展示）"""
    from app.core.config import get_settings

    s = get_settings()
    has_key = bool(s.llm_api_key)
    return {
        "code": 200,
        "msg": "ok",
        "data": {
            "modalities": ["ocr", "asr"],
            "ocr": {
                "model": "glm-4v-flash",
                "provider": "zhipu",
                "supported_formats": ["jpg", "jpeg", "png", "webp"],
                "max_size_mb": 10,
                "mock": not has_key,
                "description": "智谱 GLM-4V-Flash 课表识别，输出结构化 JSON {courses:[{course,teacher,time,location}]}",
            },
            "asr": {
                "model": "whisper-1",
                "provider": "openai-compatible",
                "supported_formats": ["webm", "mp3", "wav", "m4a"],
                "max_size_mb": 5,
                "mock": not has_key,
                "smart_mock": True,
                "description": "Whisper 语音识别，无 key 时根据时间智能推断 mock",
            },
            "has_key": has_key,
            "precision": {"ocr": 0.85 if has_key else 0.0},
        },
    }
