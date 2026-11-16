# src/services/ingest_service.py - ingestione e invalidazione cache advice
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import DocumentChunk
from src.lib.chunking import chunk_text
from src.llm.embedding_client import Embedder

log = logging.getLogger(__name__)


def senza_ripetizioni(testo: str) -> str:
    paragrafi = [p.strip() for p in testo.split("\n\n") if p.strip()]
    return "\n\n".join(dict.fromkeys(paragrafi))


class IngestService:
    """Porta un documento nell'indice e invalida la cache risposte advisor."""

    LOTTO = 64

    def __init__(
        self, session: AsyncSession, embedder: Embedder, cache: Redis | None = None
    ) -> None:
        self.session = session
        self.embedder = embedder
        self.cache = cache

    async def _invalida_cache_advice(self) -> None:
        if self.cache is None:
            return
        try:
            keys = [k async for k in self.cache.scan_iter(match="advice:*")]
            if keys:
                await self.cache.delete(*keys)
        except RedisError:
            log.warning("advice_cache_invalidate_failed")

    async def ingest(
        self,
        document_id: str,
        text: str,
        metadata: dict[str, str] | None = None,
        visibility: str = "public",
    ) -> int:
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )

        pezzi = chunk_text(senza_ripetizioni(text))
        if not pezzi:
            await self.session.commit()
            await self._invalida_cache_advice()
            return 0

        for inizio in range(0, len(pezzi), self.LOTTO):
            lotto = pezzi[inizio : inizio + self.LOTTO]
            vettori = await self.embedder.embed(lotto)
            self.session.add_all(
                [
                    DocumentChunk(
                        document_id=document_id,
                        chunk_index=inizio + i,
                        content=testo,
                        embedding=vettore,
                        chunk_metadata=metadata or {},
                        visibility=visibility,
                    )
                    for i, (testo, vettore) in enumerate(zip(lotto, vettori, strict=True))
                ]
            )

        await self.session.commit()
        await self._invalida_cache_advice()
        return len(pezzi)
