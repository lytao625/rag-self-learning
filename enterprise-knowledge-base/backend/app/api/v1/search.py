from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_search_debug
from app.db.session import get_db
from app.models import KnowledgeBase, User
from app.schemas.common import SearchRequest
from app.services import rag
from app.utils.errors import api_error, get_trace_id

router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
async def debug_search(
    request: Request,
    body: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_search_debug)],
):
    tid = get_trace_id(request)
    kb = await db.get(KnowledgeBase, body.knowledge_base_id)
    if not kb:
        raise api_error("KB_NOT_FOUND", "知识库不存在", status_code=404, trace_id=tid)
    results = await rag.hybrid_search(db, body.knowledge_base_id, body.query, top_k=body.top_k)
    return {"results": results}
