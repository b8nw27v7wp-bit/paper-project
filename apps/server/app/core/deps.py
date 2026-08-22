from fastapi import Header, Depends
from typing import Optional

# P0: 无 JWT，固定 user 1；后续接 Auth 后替换为 JWT 解析
def get_current_user_id(x_user_id: Optional[str] = Header(default=None)) -> int:
    if x_user_id and x_user_id.isdigit():
        return int(x_user_id)
    return 1
