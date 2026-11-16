# tests/test_g10.py - G10: config/cache/ready/cache advice (leva tempo)
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import Settings
from src.llm.embeddings import CachedEmbedder
from src.llm.rewriter import Riscrittura
from src.services.retrieval_service import RetrievalResult


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [[float((len(t) % 3) + 1), 0.0, 0.0] for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return [1.0, 0.0, 0.0]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embed_documents(texts)

    async def embed_one(self, text: str) -> list[float]:
        return await self.embed_query(text)


class _FakeLLM:
    def __init__(self, text: str = "Risposta [fonte-1]") -> None:
        self.text = text
        self.calls = 0
        self.model = "fake-model"

    async def complete(self, messages: object, max_tokens: int = 500) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            content=self.text, tokens_used=10, cost_eur=Decimal("0.01"), model=self.model
        )


class _FakeRetrieval:
    async def search_for_user(
        self, query_vec: list[float], role: str, top_k: int = 5
    ) -> list[RetrievalResult]:
        return [
            RetrievalResult(
                chunk_id="c1",
                document_id="faq_carte",
                content="Costo carta 10 euro",
                similarity=0.9,
            )
        ]

    async def search_hybrid(
        self,
        query_vec: list[float],
        query_text: str,
        livelli: list[str] | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        return [
            RetrievalResult(
                chunk_id="c1",
                document_id="faq_carte",
                content="Costo carta 10 euro",
                similarity=0.9,
            )
        ]


class _FakeRewriter:
    def __init__(self) -> None:
        self.calls = 0

    async def riscrivi_per_ricerca(
        self, question: str, history: list[str] | None = None
    ) -> Riscrittura:
        self.calls += 1
        return Riscrittura(testo=question, cache_hit=False, cost_eur=Decimal("0"), tokens=0)


def test_redis_url_vuoto_non_crea_client(monkeypatch) -> None:
    from src import cache

    monkeypatch.setattr(cache.settings, "redis_url", "")
    cache.get_redis.cache_clear()
    assert cache.get_redis() is None
    cache.get_redis.cache_clear()


def test_jwt_placeholder_rifiutato() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://x:x@localhost:5432/x",
            jwt_secret="cambiami_questo_segreto_lungo_32_caratteri",
        )


async def test_cache_embedding_evita_chiamata() -> None:
    import fakeredis.aioredis

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    interno = _FakeEmbedder()
    emb = CachedEmbedder(interno, r, model="m", dim=3)
    v1 = await emb.embed_query("ciao mondo")
    v2 = await emb.embed_query("ciao mondo")
    assert v1 == v2
    assert interno.calls == 1
    assert emb.hit == 1


async def test_risposta_citabile_non_cambia_con_cache_advice() -> None:
    import fakeredis.aioredis

    from src.auth.deps import UserContext
    from src.services.rag_service import RAGService

    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    llm = _FakeLLM("La carta costa 10 euro [fonte-1].")
    svc = RAGService(
        _FakeRetrieval(),  # type: ignore[arg-type]
        _FakeEmbedder(),
        llm,  # type: ignore[arg-type]
        _FakeRewriter(),  # type: ignore[arg-type]
        "PROMPT",
        cache=r,
    )
    user = UserContext(username="mbianchi", role="operator")
    a = await svc.advise("Quanto costa la carta?", user)
    b = await svc.advise("Quanto costa la carta?", user)
    assert a.answer == b.answer
    assert [c.model_dump() for c in a.citations] == [c.model_dump() for c in b.citations]
    assert llm.calls == 1


async def test_readiness_db_giu_503_cache_giu_200(monkeypatch) -> None:
    from src import main

    async def db_ko() -> main.ComponenteReady:
        return main.ComponenteReady(stato="errore", dettaglio="database non raggiungibile")

    async def cache_ko() -> main.ComponenteReady:
        return main.ComponenteReady(stato="degradata", dettaglio="cache non raggiungibile")

    monkeypatch.setattr(main, "_database", db_ko)
    monkeypatch.setattr(main, "_cache_check", cache_ko)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
        r = await ac.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["controlli"]["database"]["stato"] == "errore"

    async def db_ok() -> main.ComponenteReady:
        return main.ComponenteReady(stato="ok")

    monkeypatch.setattr(main, "_database", db_ok)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as ac:
        r2 = await ac.get("/ready")
    assert r2.status_code == 200
    assert r2.json()["controlli"]["cache"]["stato"] in {"degradata", "ok", "disattivata"}


def test_limiter_configurato() -> None:
    from src.api.advice import limiter

    assert limiter is not None


def test_prompt_version_presente_rewriter() -> None:
    from src.llm.rewriter import QueryRewriter

    rw = QueryRewriter(_FakeLLM(), "prompt v1", enabled=False)  # type: ignore[arg-type]
    assert rw.prompt_version


def test_dockerfile_non_copia_segreti() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "COPY .env" not in dockerfile
    assert "USER lipari" in dockerfile
    runtime = dockerfile.split("AS runtime", 1)[-1]
    assert "ghcr.io/astral-sh/uv" not in runtime

