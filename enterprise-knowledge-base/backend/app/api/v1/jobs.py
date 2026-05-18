from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import IngestionJob, User
from app.schemas.common import JobOut
from app.utils.errors import api_error, get_trace_id

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    request: Request,
    job_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
):
    tid = get_trace_id(request)
    job = await db.get(IngestionJob, job_id)
    if not job:
        raise api_error("JOB_NOT_FOUND", "任务不存在", status_code=404, trace_id=tid)
    return job
