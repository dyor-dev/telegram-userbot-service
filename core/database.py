from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from core.config import settings

# Neon.tech va PostgreSQL linkini asinxron asyncpg drayveri uchun moslashtirish
db_url = settings.DATABASE_URL

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# asyncpg kutubxonasi 'sslmode' o'rniga 'ssl' parametrini tushunadi
if "sslmode=" in db_url:
    db_url = db_url.replace("sslmode=", "ssl=")
if "&channel_binding=require" in db_url:
    db_url = db_url.replace("&channel_binding=require", "")

# Asinxron engine yaratish
engine = create_async_engine(
    db_url,
    echo=False,
    pool_size=10,
    max_overflow=5
)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    """Baza sessiyasini xavfsiz ochish va yopish uchun yordamchi generator."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
