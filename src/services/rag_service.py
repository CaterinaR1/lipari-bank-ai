# src/services/rag_service.py - pipeline con cache risposte advisor (leva 2)
import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.auth.acl import visible_to
from src.auth.deps import UserContext
from src.exceptions import LLMProviderError
from src.llm.client import LLMProvider
from src.llm.embedding_client import Embedder
from src.llm.rewriter import QueryRewriter
from src.llm.types import Message
from src.services.retrieval_service import RetrievalResult, RetrievalService, SearchMode
from src.types.advice import AdviceResponse, Citation

logger = logging.getLogger(__name__)

RIFIUTO = "Non ho trovato informazioni sufficienti nei documenti disponibili."
# Il modello a volte usa le parentesi larghe «fonte-1» o 【fonte-1】 invece di [fonte-1]
MARCATORE = re.compile(r"[\[\xab\u00ab\u3010]fonte-(\d+)[\]\xbb\u00bb\u3011]")
ADVICE_RESPONSE_CACHE_TTL = 900
ADVICE_RESPONSE_VERSION = "v2"


def contesto(passaggi: list[RetrievalResult]) -> str:
    return "\n\n".join(
        f"[fonte-{i}] (documento: {p.document_id})\n{p.content}"
        for i, p in enumerate(passaggi, start=1)
    )


def citazioni(risposta: str, passaggi: list[RetrievalResult]) -> list[Citation]:
    usati: list[Citation] = []
    visti: set[tuple[str, str]] = set()
    for numero in MARCATORE.findall(risposta):
        indice = int(numero) - 1
        if not 0 <= indice < len(passaggi):
            continue
        p = passaggi[indice]
        if (p.document_id, p.content) in visti:
            continue
        visti.add((p.document_id, p.content))
        usati.append(
            Citation(
                document_id=p.document_id,
                chunk_id=p.chunk_id,
                excerpt=p.content[:200],
                similarity=p.similarity,
            )
        )
    return usati


@dataclass
class Fasi:
    rewrite_ms: int = 0
    embedding_ms: int = 0
    retrieval_ms: int = 0
    prompt_ms: int = 0
    llm_ms: int = 0
    used_fallback: bool = False
    cache_hit: bool = False

    @property
    def total_ms(self) -> int:
        return (
            self.rewrite_ms + self.embedding_ms + self.retrieval_ms + self.prompt_ms + self.llm_ms
        )


@dataclass
class Generazione:
    testo: str
    tokens_used: int = 0
    cost_eur: Decimal = Decimal("0")
    degradata: bool = False
    model: str | None = None


@contextmanager
def _cronometro(fasi: Fasi, campo: str) -> Iterator[None]:
    inizio = time.perf_counter()
    try:
        yield
    finally:
        setattr(fasi, campo, int((time.perf_counter() - inizio) * 1000))


class RAGService:
    TIMEOUT_GENERAZIONE_S = 10

    def __init__(
        self,
        retrieval: RetrievalService,
        embedder: Embedder,
        llm: LLMProvider,
        rewriter: QueryRewriter,
        prompt: str,
        mode: SearchMode = "vector",
        cache: Redis | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.embedder = embedder
        self.llm = llm
        self.rewriter = rewriter
        self.prompt = prompt
        self.mode = mode
        self.cache = cache

    def _chiave_risposta(self, question: str, user: UserContext) -> str:
        livelli = ",".join(visible_to(user.role))
        corpo = (
            f"{ADVICE_RESPONSE_VERSION}\x1f{user.role}\x1f{livelli}\x1f{self.prompt}\x1f{question}"
        )
        return f"advice:{hashlib.sha256(corpo.encode()).hexdigest()}"

    async def _risposta_cache(self, key: str) -> AdviceResponse | None:
        if self.cache is None:
            return None
        try:
            raw = await self.cache.get(key)
        except RedisError:
            return None
        if not raw:
            return None
        try:
            data: Any = json.loads(raw)
            return AdviceResponse.model_validate(data)
        except Exception:
            return None

    async def _salva_risposta_cache(self, key: str, resp: AdviceResponse) -> None:
        if self.cache is None:
            return
        try:
            await self.cache.setex(key, ADVICE_RESPONSE_CACHE_TTL, resp.model_dump_json())
        except RedisError:
            return

    async def advise(
        self,
        question: str,
        user: UserContext,
        history: list[str] | None = None,
    ) -> AdviceResponse:
        fasi = Fasi()
        cache_key = self._chiave_risposta(question, user)

        with _cronometro(fasi, "rewrite_ms"):
            rw = await self.rewriter.riscrivi_per_ricerca(question, history)
            search_query = rw.testo

        cached_resp = await self._risposta_cache(cache_key)
        if cached_resp is not None:
            fasi.cache_hit = True
            logger.info(
                "advice_completata",
                extra={
                    "username": user.username,
                    "role": user.role,
                    "chunk_count": len(cached_resp.citations),
                    "chunk_ids": [c.chunk_id for c in cached_resp.citations],
                    "history_turns": len(history or []),
                    **asdict(fasi),
                    "total_ms": fasi.total_ms,
                },
            )
            return cached_resp

        with _cronometro(fasi, "embedding_ms"):
            query_vec = await self.embedder.embed_one(search_query)

        with _cronometro(fasi, "retrieval_ms"):
            if self.mode == "hybrid":
                chunks = await self.retrieval.search_hybrid(
                    query_vec, question, livelli=visible_to(user.role)
                )
            else:
                chunks = await self.retrieval.search_for_user(query_vec, user.role)

        if chunks:
            with _cronometro(fasi, "prompt_ms"):
                messaggi = [
                    Message(role="system", content=self.prompt),
                    Message(
                        role="user",
                        content=f"CONTESTO\n{contesto(chunks)}\n\nDOMANDA\n{question}",
                    ),
                ]
            with _cronometro(fasi, "llm_ms"):
                gen = await self._generate_or_degrade(messaggi, chunks)
        else:
            gen = Generazione(RIFIUTO)
        fasi.used_fallback = gen.degradata

        total_cost = Decimal(str(gen.cost_eur)) + rw.cost_eur
        total_tokens = int(gen.tokens_used) + int(rw.tokens)
        risposta = AdviceResponse(
            answer=gen.testo,
            citations=[] if RIFIUTO in gen.testo else citazioni(gen.testo, chunks),
            tokens_used=total_tokens,
            cost_eur=float(total_cost),
            model=gen.model,
            rewritten_query=search_query,
        )
        await self._salva_risposta_cache(cache_key, risposta)

        logger.info(
            "advice_completata",
            extra={
                "username": user.username,
                "role": user.role,
                "chunk_count": len(chunks),
                "chunk_ids": [r.chunk_id for r in chunks],
                "history_turns": len(history or []),
                **asdict(fasi),
                "total_ms": fasi.total_ms,
            },
        )
        return risposta

    async def _generate_or_degrade(
        self, messaggi: list[Message], chunks: list[RetrievalResult]
    ) -> Generazione:
        try:
            async with asyncio.timeout(self.TIMEOUT_GENERAZIONE_S):
                risposta = await self.llm.complete(messaggi, max_tokens=500)
            return Generazione(
                risposta.content, risposta.tokens_used, risposta.cost_eur, model=risposta.model
            )
        except (LLMProviderError, TimeoutError):
            logger.warning("generator_non_disponibile_fallback_su_chunk")
            estratti = "\n\n".join(
                f"[fonte-{i}] {r.document_id}\n{r.content}"
                for i, r in enumerate(chunks[:3], start=1)
            )
            return Generazione(
                "⚠️ Risposta parziale: il servizio di sintesi non è momentaneamente "
                "disponibile. Di seguito i passaggi dei documenti più pertinenti "
                f"alla tua domanda.\n\n{estratti}",
                degradata=True,
            )
