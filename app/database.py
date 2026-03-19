from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# async engine using asyncpg
engine = create_async_engine(
    settings.database_url,
    echo=True,
    pool_size=20,
    max_overflow=10,
)

# session factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


# dependency for FastAPI routes
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session