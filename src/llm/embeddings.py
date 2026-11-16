# src/llm/embeddings.py - type Redis explicitly to satisfy lint
import hashlib
import json
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.llm.embedding_client import Embedder

log = logging.getLogger(__name__)


class CachedEmbedder:
    """Cache per-testo degli embedding. Redis opzionale e best-effort."""

    def __init__(
        self,
        interno: Embedder,
        redis: Redis | None,
        ttl: int = 86400,
        prefix: str = "embed",
        model: str = "unknown",
        dim: int = 0,
    ) -> None:
        self.interno = interno
        self.redis = redis
        self.ttl = ttl
        self.prefix = prefix
        self.model = model
        self.dim = dim
        self.hit = 0
        self.miss = 0

    def _chiave(self, testo: str) -> str:
        corpo = f"{self.model}:{self.dim}:{testo}".encode()
        return f"{self.prefix}:{hashlib.sha256(corpo).hexdigest()}"

    async def _get(self, key: str) -> list[float] | None:
        if self.redis is None:
            return None
        try:
            raw = await self.redis.get(key)
        except RedisError:
            return None
        if raw is None:
            return None
        try:
            val = json.loads(raw)
            if isinstance(val, list):
                return [float(x) for x in val]
        except Exception:
            return None
        return None

    async def _set(self, key: str, value: list[float]) -> None:
        if self.redis is None:
            return
        try:
            await self.redis.setex(key, self.ttl, json.dumps(value))
        except RedisError:
            return

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.redis is None:
            self.miss += len(texts)
            return await self.interno.embed_documents(texts)
        keys = [self._chiave(t) for t in texts]
        try:
            cached = await self.redis.mget(keys)
        except RedisError:
            self.miss += len(texts)
            return await self.interno.embed_documents(texts)
        risultati: list[list[float] | None] = [None] * len(texts)
        mancanti_idx: list[int] = []
        for i, raw in enumerate(cached):
            if raw is None:
                mancanti_idx.append(i)
                continue
            try:
                val = json.loads(raw)
                if isinstance(val, list):
                    risultati[i] = [float(x) for x in val]
                    self.hit += 1
                else:
                    mancanti_idx.append(i)
            except Exception:
                mancanti_idx.append(i)
        if mancanti_idx:
            self.miss += len(mancanti_idx)
            calcolati = await self.interno.embed_documents([texts[i] for i in mancanti_idx])
            for idx, vettore in zip(mancanti_idx, calcolati, strict=True):
                risultati[idx] = vettore
                await self._set(keys[idx], vettore)
        return [r for r in risultati if r is not None]

    async def embed_query(self, text: str) -> list[float]:
        key = self._chiave(text)
        cached = await self._get(key)
        if cached is not None:
            self.hit += 1
            return cached
        self.miss += 1
        vettore = await self.interno.embed_query(text)
        await self._set(key, vettore)
        return vettore

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_documents(texts)

    async def embed_one(self, text: str) -> list[float]:
        return await self.embed_query(text)
