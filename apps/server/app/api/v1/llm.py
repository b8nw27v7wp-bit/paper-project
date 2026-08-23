from fastapi import APIRouter

from app.core.llm import PROVIDER_MAP

router = APIRouter()

@router.get("/llm/models")
def list_models():
    return {"code":200,"msg":"ok","data": [{"provider":k, **v} for k,v in PROVIDER_MAP.items()]}
