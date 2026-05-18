from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models import AuditLog, User
from app.schemas.common import AuditOut
from app.schemas.common import RuntimeLLMConfigOut, RuntimeLLMConfigUpdate

router_admin = APIRouter(prefix="/admin", tags=["admin"])


@router_admin.get("/audit-logs", response_model=list[AuditOut])
async def audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    limit: int = 100,
):
    r = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    return list(r.scalars().all())


router_cfg = APIRouter(prefix="/config", tags=["config"])


@router_cfg.get("/llm", response_model=RuntimeLLMConfigOut)
async def get_llm_config(_: Annotated[User, Depends(get_current_user)]):
    s = get_settings()
    return RuntimeLLMConfigOut(
        llm_model=s.llm_model,
        embedding_model=s.embedding_model,
        openai_api_base=s.openai_api_base,
        has_api_key=bool(s.openai_api_key),
    )


@router_cfg.post("/llm")
async def update_llm_config(
    body: RuntimeLLMConfigUpdate,
    _: Annotated[User, Depends(get_current_user)],
):
    # 生产环境应写入密钥管理服务；此处仅演示：运行时环境变量不可通过 API 修改，仅返回提示
    return {"ok": False, "message": "请通过环境变量或部署配置修改 LLM 连接信息（OPENAI_API_BASE / LLM_MODEL 等）"}
