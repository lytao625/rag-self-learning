import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import SessionLocal, get_db
from app.models import ChatMessage, ChatSession, KnowledgeBase, User
from app.schemas.common import ChatRequest
from app.services import rag
from app.utils.audit import write_audit
from app.utils.errors import api_error, get_trace_id

router = APIRouter(prefix="/chat", tags=["chat"])


def _build_context(hits: list[dict]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        meta = h.get("metadata") or {}
        src = meta.get("source", "")
        parts.append(f"[片段{i}] 来源:{src}\n{h.get('content', '')}")
    return "\n\n".join(parts)


@router.post("")
async def chat(
    request: Request,
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    tid = get_trace_id(request)
    kb = await db.get(KnowledgeBase, body.knowledge_base_id)
    if not kb:
        raise api_error("KB_NOT_FOUND", "知识库不存在", status_code=404, trace_id=tid)

    session: ChatSession | None = None
    if body.session_id:
        session = await db.get(ChatSession, body.session_id)
        if not session or session.user_id != user.id:
            raise api_error("SESSION_INVALID", "会话无效", status_code=400, trace_id=tid)
        if session.knowledge_base_id != body.knowledge_base_id:
            raise api_error("SESSION_KB_MISMATCH", "会话与知识库不匹配", status_code=400, trace_id=tid)
    else:
        session = ChatSession(
            user_id=user.id,
            knowledge_base_id=body.knowledge_base_id,
            title=(body.message[:48] + "…") if len(body.message) > 48 else body.message,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

    hits = await rag.hybrid_search(db, body.knowledge_base_id, body.message, top_k=body.top_k)
    citations = [
        {
            "chunk_id": h["chunk_id"],
            "content": h["content"][:500],
            "score": h["score"],
            "metadata": h["metadata"],
        }
        for h in hits
    ]
    ctx = _build_context(hits)

    hist = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.asc())
        .limit(20)
    )
    prior = list(hist.scalars().all())
    llm_messages: list[dict[str, str]] = []
    for m in prior:
        llm_messages.append({"role": m.role, "content": m.content})

    user_turn = f"参考资料:\n{ctx}\n\n用户问题:\n{body.message}"
    llm_messages.append({"role": "user", "content": user_turn})

    um = ChatMessage(session_id=session.id, role="user", content=body.message, citations_json=None)
    db.add(um)
    await db.commit()

    if not body.stream:

        async def collect():
            buf: list[str] = []
            async for p in rag.stream_llm_answer(llm_messages):
                buf.append(p)
            return "".join(buf)

        answer = await collect()
        am = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=answer,
            citations_json={"items": citations},
        )
        db.add(am)
        await db.commit()
        await write_audit(
            db,
            user_id=user.id,
            action="chat",
            resource_type="session",
            resource_id=session.id,
            detail={"kb_id": body.knowledge_base_id},
            ip=request.client.host if request.client else None,
        )
        return {
            "session_id": session.id,
            "answer": answer,
            "citations": citations,
        }

    sid = session.id
    client_ip = request.client.host if request.client else None

    async def event_gen():
        full: list[str] = []
        yield f"event: citation\ndata: {json.dumps({'items': citations}, ensure_ascii=False)}\n\n"
        try:
            async for piece in rag.stream_llm_answer(llm_messages):
                full.append(piece)
                yield f"event: answer_delta\ndata: {json.dumps({'text': piece}, ensure_ascii=False)}\n\n"
            text = "".join(full)
            async with SessionLocal() as sdb:
                am = ChatMessage(
                    session_id=sid,
                    role="assistant",
                    content=text,
                    citations_json={"items": citations},
                )
                sdb.add(am)
                await sdb.commit()
                await write_audit(
                    sdb,
                    user_id=user.id,
                    action="chat",
                    resource_type="session",
                    resource_id=sid,
                    detail={"kb_id": body.knowledge_base_id},
                    ip=client_ip,
                )
            yield f"event: done\ndata: {json.dumps({'session_id': sid}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
