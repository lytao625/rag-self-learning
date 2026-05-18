from fastapi import APIRouter

from app.api.v1 import admin_config, auth, chat, jobs, knowledge_bases, search, sessions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(knowledge_bases.router)
api_router.include_router(jobs.router)
api_router.include_router(chat.router)
api_router.include_router(sessions.router)
api_router.include_router(search.router)
api_router.include_router(admin_config.router_admin)
api_router.include_router(admin_config.router_cfg)
