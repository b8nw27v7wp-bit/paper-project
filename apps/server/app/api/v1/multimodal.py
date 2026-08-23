from fastapi import APIRouter, File, HTTPException, UploadFile

from app.multimodal.asr import whisper_asr
from app.multimodal.ocr import qwen_ocr

router = APIRouter()

@router.post("/multimodal/ocr")
async def ocr(file: UploadFile = File(...)):
    if file.size and file.size > 10*1024*1024:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"图片>10M"})
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"空文件"})
    res = await qwen_ocr(data)
    return {"code":200,"msg":"ok","data":res}

@router.post("/multimodal/asr")
async def asr(file: UploadFile = File(...)):
    if file.size and file.size > 5*1024*1024:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"音频>5M"})
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"空文件"})
    res = await whisper_asr(data)
    return {"code":200,"msg":"ok","data":res}
