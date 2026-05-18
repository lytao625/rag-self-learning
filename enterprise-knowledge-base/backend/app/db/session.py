from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base

settings = get_settings()


def ensure_sqlite_parent_dir() -> None:
    """SQLite 不会自动创建父目录；连接前必须保证目录存在。"""
    url = make_url(settings.database_url)
    if url.get_dialect().name != "sqlite":
        return
    db = url.database
    if not db or db == ":memory:":
        return
    Path(db).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401

    ensure_sqlite_parent_dir()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
