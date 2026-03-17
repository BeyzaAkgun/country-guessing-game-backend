from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings

# Remove ?ssl=require from URL if present
database_url = settings.database_url.replace("?ssl=require", "").replace("&ssl=require", "")

# SSL + disable prepared statements (required for Supabase transaction pooler)
connect_args = {}
if "supabase.co" in database_url or settings.is_production:
    connect_args["ssl"] = "require"
    connect_args["statement_cache_size"] = 0  # required for pgbouncer/Supabase pooler

engine = create_async_engine(
    database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=connect_args,
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