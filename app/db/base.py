#base.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

# Remove ssl query args from URL if present
# asyncpg will handle SSL through connect_args, and prepared statements must be disabled
# when using pgbouncer-style pooling (Fly Postgres, Supabase, etc.).
database_url = (
    settings.database_url
    .replace("?ssl=require", "")
    .replace("&ssl=require", "")
    .replace("?sslmode=require", "")
    .replace("&sslmode=require", "")
)

connect_args = {
    "statement_cache_size": 0,  # required for pgbouncer/Supabase/Fly poolers
}
if "supabase.co" in database_url or settings.is_production or "sslmode=require" in settings.database_url or "ssl=require" in settings.database_url:
    connect_args["ssl"] = "require"

engine = create_async_engine(
    database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args,
    # Also disable at engine level to cover all session types
    execution_options={"compiled_cache": None},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise