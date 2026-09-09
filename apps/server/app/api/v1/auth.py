"""Auth 2接口：login / register（对齐 05-API 3.1）"""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.core.ratelimit import check_rate_limit
from app.models.user import User

logger = logging.getLogger("app.auth")
router = APIRouter()
settings = get_settings()

class LoginReq(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=64)

class RegisterReq(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=64)
    major: str | None = Field(default=None, max_length=64)

def _hash_pwd(pwd: str) -> str:
    # 新注册/改密统一 bcrypt（仅缺 bcrypt 后端时回退 sha256，不批量改旧数据）
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.hash(pwd)
    except Exception as e:
        # R3：sha256 回退必须可见——缺 bcrypt 后端时打 warning（requirements 含 passlib[bcrypt]，正常环境不应触发）
        logger.warning("bcrypt backend missing, fallback to sha256 (pip install 'passlib[bcrypt]'): %s", e)
        import hashlib
        return hashlib.sha256(pwd.encode()).hexdigest()

def _is_bcrypt_hash(hashed: str) -> bool:
    return hashed.startswith(("$2a$", "$2b$", "$2y$"))

def _verify_pwd(pwd: str, hashed: str) -> bool:
    # 双格式校验：bcrypt 优先，sha256 兼容旧（不迁移旧数据）
    if not hashed:
        return False
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        try:
            if ctx.verify(pwd, hashed):
                return True
        except Exception:
            pass  # 非 bcrypt 旧 hash 走 sha256 分支
    except Exception:
        pass
    try:
        import hashlib
        return hashlib.sha256(pwd.encode()).hexdigest() == hashed
    except Exception:
        return False

def _create_token(user_id: int, username: str) -> str:
    from jose import jwt
    exp = datetime.now(UTC) + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": str(user_id), "username": username, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

@router.post("/auth/register", status_code=201)
def register(payload: RegisterReq, request: Request, session: Session = Depends(get_session)):
    # 未登录接口无 user_id：user 段固定哨兵 0，按 IP+路径限流（key=rate:0:ip:path，见 ratelimit），
    # 避免与登录用户桶（uid>=1）混淆；阈值 AUTH_REGISTER_LIMIT=5/min（独立于 plans 5/min 语义）。
    check_rate_limit(request, 0)
    exists = session.exec(select(User).where(User.username == payload.username)).first()
    if exists:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"用户名已存在"})
    user = User(username=payload.username, password_hash=_hash_pwd(payload.password), major=payload.major)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"code":201,"msg":"ok","data":{"id":user.id,"username":user.username,"major":user.major}}

@router.post("/auth/login")
def login(payload: LoginReq, request: Request, session: Session = Depends(get_session)):
    # 同上哨兵 0 限流；阈值 AUTH_LOGIN_LIMIT=10/min。429 走现有包络 {code:42901}，由 main.py 透传。
    check_rate_limit(request, 0)
    user = session.exec(select(User).where(User.username == payload.username)).first()
    if not user or not _verify_pwd(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail={"code":40101,"msg":"用户名或密码错误"})
    token = _create_token(user.id, user.username)  # type: ignore
    return {"code":200,"msg":"ok","data":{"token":token,"user":{"id":user.id,"username":user.username,"major":user.major}}}

@router.get("/auth/me")
def me(user_id: int = Depends(get_current_user_id)):
    return {"code":200,"msg":"ok","data":{"user_id": user_id}}


@router.get("/auth/verify")
def verify(user_id: int = Depends(get_current_user_id)):
    return {"code":200,"msg":"ok","data":{"user_id": user_id}}
