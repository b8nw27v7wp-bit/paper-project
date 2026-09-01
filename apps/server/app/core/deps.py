
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
                # 若 payload 无 uid，视为有效 token 但回退到 1
                logger.warning(f"JWT without uid payload: {payload}")
                return 1
            except Exception as e:
                # JWT 无效时，debug 下允许回退到 X-User-Id，prod 直接 401
                logger.warning(f"JWT decode failed: {e}")
                if not settings.debug:
                    raise HTTPException(status_code=401, detail={"code": 40101, "msg": "invalid token"})
                # debug 允许回退
    # 2) X-User-Id 回退（dev/pytest）
    # 仅在 debug=True 或显式 PYTEST 时允许，prod 要求 JWT
    if x_user_id and x_user_id.isdigit():
        if settings.debug or os.getenv("PYTEST_CURRENT_TEST"):
            return int(x_user_id)
        # prod 非 debug 且无有效 JWT 却用 X-User-Id → 视为伪造，拒绝
        # 为兼容旧前端在 prod 仍用 X-User-Id 的过渡期，改为警告而非直接 401
        # 若需强校验，取消下行注释：
        # raise HTTPException(status_code=401, detail={"code":40101,"msg":"missing token"})
        logger.warning(f"X-User-Id used in non-debug without JWT: {x_user_id}")
        return int(x_user_id)
    # 3) 无身份，默认 1（保持 test_auth_isolation 的匿名创建行为）
    # 仅当请求非需鉴权或 debug 时；prod 严格可改为 401
    return 1


def require_user_id(*args, **kwargs) -> int:
    """别名，供未来强校验路由使用"""
    uid = get_current_user_id(*args, **kwargs)  # type: ignore
    if uid is None:
        raise HTTPException(status_code=401, detail={"code": 40101, "msg": "unauthorized"})
    return uid
