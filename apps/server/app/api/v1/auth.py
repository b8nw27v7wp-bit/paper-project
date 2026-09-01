"""Auth 2接口：login / register（对齐 05-API 3.1）"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import get_session
from app.core.deps import get_current_user_id
from app.models.user import User

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
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.hash(pwd)
    except Exception:
        import hashlib
        return hashlib.sha256(pwd.encode()).hexdigest()

def _verify_pwd(pwd: str, hashed: str) -> bool:
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        return ctx.verify(pwd, hashed)
    except Exception:
        import hashlib
        return hashlib.sha256(pwd.encode()).hexdigest() == hashed

def _create_token(user_id: int, username: str) -> str:
    from jose import jwt
    exp = datetime.now(UTC) + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": str(user_id), "username": username, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

@router.post("/auth/register", status_code=201)
def register(payload: RegisterReq, session: Session = Depends(get_session)):
    exists = session.exec(select(User).where(User.username == payload.username)).first()
    if exists:
        raise HTTPException(status_code=400, detail={"code":40001,"msg":"用户名已存在"})
    user = User(username=payload.username, password_hash=_hash_pwd(payload.password), major=payload.major)
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"code":201,"msg":"ok","data":{"id":user.id,"username":user.username,"major":user.major}}

@router.post("/auth/login")
def login(payload: LoginReq, session: Session = Depends(get_session)):
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
