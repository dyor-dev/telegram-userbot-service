from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

db_url = settings.DATABASE_URL

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

if "sslmode=" in db_url:
    db_url = db_url.replace("sslmode=", "ssl=")
if "&channel_binding=require" in db_url:
    db_url = db_url.replace("&channel_binding=require", "")

# Ulanishni doimiy issiq va tezkor ushlab turuvchi sozlamalar
engine = create_async_engine(
    db_url,
    echo=False,
    pool_size=15,
    max_overflow=10,
    pool_pre_ping=True,      # Har bir so'rovdan oldin aloqani tezkor tekshiradi (qotib qolmaslik uchun)
    pool_recycle=300,        # Har 5 daqiqada ulanishni yangilab, Neon bazani uxlab qolishdan asraydi
)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
