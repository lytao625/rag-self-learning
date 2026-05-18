from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models import User, UserRole
from app.utils.errors import api_error, get_trace_id

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User:
    tid = get_trace_id(request)
    if cred is None or cred.scheme.lower() != "bearer":
        raise api_error("UNAUTHORIZED", "缺少或无效的认证信息", status_code=401, trace_id=tid)
    payload = decode_token(cred.credentials)
    if not payload or "sub" not in payload:
        raise api_error("UNAUTHORIZED", "令牌无效或已过期", status_code=401, trace_id=tid)
    uid = payload["sub"]
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise api_error("UNAUTHORIZED", "用户不存在", status_code=401, trace_id=tid)
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.admin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def require_kb_write(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in (
        UserRole.admin.value,
        UserRole.kb_admin.value,
        UserRole.contributor.value,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权上传或管理文档")
    return user


def require_kb_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in (UserRole.admin.value, UserRole.kb_admin.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要知识库管理员权限")
    return user


def require_search_debug(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in (UserRole.admin.value, UserRole.kb_admin.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可使用调试检索")
    return user
