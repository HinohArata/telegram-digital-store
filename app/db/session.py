import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine
)
from app.config import settings

logger = logging.getLogger(__name__)

# Trik kompatibilitas Supabase PgBouncer (Transaction Pooler):
# Matikan prepared statements cache jika menggunakan asyncpg
connect_args = {}
if "postgresql+asyncpg" in settings.DATABASE_URL:
    # Memastikan asyncpg kompatibel dengan PgBouncer Supabase port 6543
    connect_args = {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0
    }

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency helper untuk FastAPI atau context manager per request."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
