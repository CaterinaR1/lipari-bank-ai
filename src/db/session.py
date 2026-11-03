# src/db/session.py — l'engine async, il pool, e la sessione per richiesta
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)

# expire_on_commit=False: dopo il commit gli oggetti restano leggibili, senza una nuova query
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Una sessione per richiesta. Il commit lo decide il service: se esce un errore, la
    sessione si chiude senza commit e la transazione si annulla."""
    async with AsyncSessionLocal() as session:
        yield session
