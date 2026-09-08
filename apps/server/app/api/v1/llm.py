from fastapi import APIRouter, Depends

from app.core.deps import get_current_user_id
from app.core.llm import PROVIDER_MAP

router = APIRouter()

@router.get("/llm/models")
def list_models(user_id: int = Depends(get_current_user_id)):
    return {"code":200,"msg":"ok","data": [{"provider":k, **v} for k,v in PROVIDER_MAP.items()]}
