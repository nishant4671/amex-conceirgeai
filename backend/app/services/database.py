from collections.abc import AsyncGenerator
import logging
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.core.config import settings

logger = logging.getLogger("database")

# Setup async engine with connection pooling
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to retrieve database session in request context."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def verify_db_connection() -> bool:
    """Verifies connection to PostgreSQL on startup."""
    try:
        async with AsyncSessionLocal() as session:
            # Simple select statement to check DB response
            from sqlalchemy.sql import text
            await session.execute(text("SELECT 1"))
            logger.info("PostgreSQL database connection verified successfully.")
            return True
    except Exception as e:
        logger.error(f"PostgreSQL connection verification failed: {e}")
        return False
