from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.common import LoginRequest, TokenResponse
from app.utils.audit import write_audit
from app.utils.errors import api_error, get_trace_id

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tid = get_trace_id(request)
    r = await db.execute(select(User).where(User.username == body.username))
    user = r.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        await write_audit(
            db,
            user_id=None,
            action="login_failed",
            resource_type="user",
            resource_id=body.username,
            detail=None,
            ip=request.client.host if request.client else None,
        )
        raise api_error("INVALID_CREDENTIALS", "用户名或密码错误", status_code=401, trace_id=tid)
    token = create_access_token(user.id, extra={"role": user.role})
    await write_audit(
        db,
        user_id=user.id,
        action="login",
        resource_type="user",
        resource_id=user.id,
        ip=request.client.host if request.client else None,
    )
    return TokenResponse(access_token=token, role=user.role, user_id=user.id)


@router.post("/logout")
async def logout(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await write_audit(
        db,
        user_id=user.id,
        action="logout",
        resource_type="user",
        resource_id=user.id,
        ip=request.client.host if request.client else None,
    )
    return {"ok": True}
