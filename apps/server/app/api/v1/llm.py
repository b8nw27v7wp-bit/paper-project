from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.deps import get_current_user_id
from app.core.llm import PROVIDER_MAP, UnifiedClient

router = APIRouter()


# 中文注释：小结请求体，text 限 1-2000 字，max_len 默认 12
class SummarizeIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    max_len: int = Field(default=12, ge=1)


@router.get("/llm/models")
def list_models(user_id: int = Depends(get_current_user_id)):
    return {"code":200,"msg":"ok","data": [{"provider":k, **v} for k,v in PROVIDER_MAP.items()]}


@router.post("/llm/summarize")
async def summarize(payload: SummarizeIn, user_id: int = Depends(get_current_user_id)):
    # 中文注释：用统一 LLM 生成中文一句话小结，失败时抛 50001 由前端回退拼装
    prompt = f"用一句话总结，不超过{payload.max_len}字，只要结论不要标点赘述：{payload.text}"
    try:
        raw = await UnifiedClient().chat(messages=[{"role": "user", "content": prompt}])
        title = (raw or "").strip()[: payload.max_len]
        if not title:
            raise ValueError("empty llm result")
        return {"code": 200, "msg": "ok", "data": {"title": title}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": 50001, "msg": f"LLM小结失败: {e}"})
