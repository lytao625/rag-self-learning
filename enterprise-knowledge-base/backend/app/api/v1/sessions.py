from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import ChatMessage, ChatSession, User
from app.schemas.common import ChatMessageOut, SessionOut
from app.utils.errors import api_error, get_trace_id

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    r = await db.execute(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.created_at.desc())
    )
    return list(r.scalars().all())


@router.get("/{session_id}/messages", response_model=list[ChatMessageOut])
async def session_messages(
    request: Request,
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    tid = get_trace_id(request)
    s = await db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise api_error("SESSION_INVALID", "会话不存在", status_code=404, trace_id=tid)
    r = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    )
    return list(r.scalars().all())


@router.delete("/{session_id}")
async def delete_session(
    request: Request,
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    tid = get_trace_id(request)
    s = await db.get(ChatSession, session_id)
    if not s or s.user_id != user.id:
        raise api_error("SESSION_INVALID", "会话不存在", status_code=404, trace_id=tid)
    await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    await db.delete(s)
    await db.commit()
    return {"ok": True}
