
import logging
import os

from fastapi import Header, HTTPException

from app.core.config import get_settings

logger = logging.getLogger("app.auth")


# P0 已加固：优先校验 Authorization: Bearer JWT，X-User-Id 仅 dev/pytest 兼容
def get_current_user_id(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> int:
    settings = get_settings()
    # 1) 优先 JWT
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if token:
            try:
                from jose import jwt  # type: ignore

                payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
                # 约定 sub 或 user_id
                uid = payload.get("sub") or payload.get("user_id") or payload.get("uid")
                if uid is not None:
                    try:
                        return int(uid)
                    except Exception:
                        pass
                # payload 无有效 uid：视为无效 token，直接 401（不再回退 user 1）
                logger.warning(f"JWT without valid uid payload: {payload}")
                raise HTTPException(status_code=401, detail={"code": 40101, "msg": "invalid token"})
            except HTTPException:
                raise
            except Exception as e:
                # JWT 无效时，debug 下允许回退到 X-User-Id，prod 直接 401
                logger.warning(f"JWT decode failed: {e}")
                if not settings.debug:
                    raise HTTPException(status_code=401, detail={"code": 40101, "msg": "invalid token"})
                # debug 允许回退
    # 2) X-User-Id 回退（dev/pytest）
    # 仅 debug=True 或 PYTEST 环境允许；prod（debug=False）无有效 JWT 一律强拒（L6）
    _dev_fallback = settings.debug or os.getenv("PYTEST_CURRENT_TEST")
    if x_user_id and x_user_id.isdigit():
        if _dev_fallback:
            return int(x_user_id)
        # prod 用 X-User-Id 伪造身份：直接 401
        raise HTTPException(status_code=401, detail={"code": 40101, "msg": "missing token"})
    # 3) 无任何身份：dev/pytest 默认 user 1（保持匿名创建行为），prod 强拒 401
    if _dev_fallback:
        return 1
    raise HTTPException(status_code=401, detail={"code": 40101, "msg": "missing token"})


def require_user_id(*args, **kwargs) -> int:
    """别名，供未来强校验路由使用（与 get_current_user_id 同签名兼容）"""
    uid = get_current_user_id(*args, **kwargs)  # type: ignore
    if not isinstance(uid, int) or isinstance(uid, bool) or uid < 1:
        raise HTTPException(status_code=401, detail={"code": 40101, "msg": "unauthorized"})
    return uid
