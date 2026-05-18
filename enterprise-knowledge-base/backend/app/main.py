import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import func, select, text

from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal, engine, init_db
from app.models import User, UserRole
from app.utils.errors import new_trace_id

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def seed_demo_users() -> None:
    async with SessionLocal() as db:
        r = await db.execute(select(func.count()).select_from(User))
        if (r.scalar() or 0) > 0:
            return
        rows = [
            User(
                username="admin",
                password_hash=hash_password("admin123"),
                role=UserRole.admin.value,
            ),
            User(
                username="kbadmin",
                password_hash=hash_password("kbadmin123"),
                role=UserRole.kb_admin.value,
            ),
            User(
                username="contributor",
                password_hash=hash_password("contrib123"),
                role=UserRole.contributor.value,
            ),
            User(
                username="user",
                password_hash=hash_password("user123"),
                role=UserRole.user.value,
            ),
        ]
        for u in rows:
            db.add(u)
        await db.commit()
        log.info(
            "Seeded demo users: admin/admin123, kbadmin/kbadmin123, "
            "contributor/contrib123, user/user123"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    Path(s.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(s.chroma_path).mkdir(parents=True, exist_ok=True)
    await init_db()
    await seed_demo_users()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
settings = get_settings()


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": exc.errors().__str__(),
                "trace_id": new_trace_id(),
            }
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    request.state.trace_id = new_trace_id()
    return await call_next(request)


app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"ready": True, "database": True}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "database": False, "error": str(e)[:200]},
        )
