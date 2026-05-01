import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "")

engine = create_async_engine(DATABASE_URL, echo=False) if DATABASE_URL else None

async_session_factory: async_sessionmaker | None = (
    async_sessionmaker(engine, expire_on_commit=False) if engine else None
)


async def get_db() -> AsyncGenerator[AsyncSession | None, None]:
    if async_session_factory is None:
        yield None
        return
    async with async_session_factory() as session:
        yield session
