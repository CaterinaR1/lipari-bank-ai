# src/llm/rewriter.py - riscrittura query con cache Redis opzionale e metadati costo
import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.llm.client import LLMProvider
from src.llm.prompt import load_prompt
from src.llm.types import Message

log = logging.getLogger(__name__)

DEFAULT_PROMPT_VERSION = "v1"


@dataclass
class Riscrittura:
    testo: str
    cache_hit: bool = False
    cost_eur: Decimal = Decimal("0")
    tokens: int = 0


class QueryRewriter:
    """Porta la domanda in una forma cercabile; opzionalmente con cache condivisa."""

    MAX_TOKENS_RISCRITTURA = 200

    def __init__(
        self,
        llm: LLMProvider,
        prompt: str,
        enabled: bool = True,
        cache: Redis | None = None,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        ttl_seconds: int = 3600,
    ) -> None:
        self.llm = llm
        self.prompt = prompt
        self.enabled = enabled
        self.cache = cache
        self.prompt_version = prompt_version
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, Riscrittura] = {}

    def _chiave(self, question: str, history: list[str] | None) -> str:
        coda = "\n".join(history[-3:]) if history else ""
        impronta = f"{self.prompt_version}\x1f{question}\x1f{coda}"
        return f"rewrite:{hashlib.sha256(impronta.encode()).hexdigest()}"

    async def _leggi_cache(self, key: str) -> Riscrittura | None:
        if (val := self._cache.get(key)) is not None:
            return Riscrittura(val.testo, True, Decimal("0"), 0)
        if self.cache is None:
            return None
        try:
            raw = await self.cache.get(key)
        except RedisError:
            return None
        if raw is None:
            return None
        return Riscrittura(str(raw), True, Decimal("0"), 0)

    async def _scrivi_cache(self, key: str, ris: Riscrittura) -> None:
        self._cache[key] = ris
        if self.cache is None:
            return
        try:
            await self.cache.setex(key, self.ttl_seconds, ris.testo)
        except RedisError:
            return

    async def _riscrivi(self, question: str, history: list[str] | None) -> Riscrittura | None:
        coda = "\n".join(history[-3:]) if history else ""
        try:
            risposta = await self.llm.complete(
                [
                    Message(role="system", content=self.prompt),
                    Message(role="user", content=f"{coda}\n\nDomanda: {question}".strip()),
                ],
                max_tokens=self.MAX_TOKENS_RISCRITTURA,
            )
        except Exception:
            log.warning("rewriter.fallito", extra={"domanda": question})
            return None
        riscritta = risposta.content.strip().strip('"')
        if not riscritta or len(riscritta) > 4 * len(question) + 80:
            log.warning("rewriter.scartata", extra={"uscita": riscritta[:120]})
            return None
        return Riscrittura(
            riscritta, False, Decimal(str(risposta.cost_eur)), int(risposta.tokens_used)
        )

    async def riscrivi_per_ricerca(
        self, question: str, history: list[str] | None = None
    ) -> Riscrittura:
        if not self.enabled:
            return Riscrittura(question)
        key = self._chiave(question, history)
        cached = await self._leggi_cache(key)
        if cached is not None:
            return cached
        ris = await self._riscrivi(question, history)
        if ris is None:
            return Riscrittura(question)
        await self._scrivi_cache(key, ris)
        return ris

    async def rewrite(self, question: str, history: list[str] | None = None) -> str:
        if not self.enabled:
            return question
        ris = await self._riscrivi(question, history)
        return ris.testo if ris else question

    async def rewrite_cached(self, question: str, history: list[str] | None = None) -> str:
        return (await self.riscrivi_per_ricerca(question, history)).testo


def get_rewriter(
    llm: LLMProvider,
    prompt: str | None = None,
    cache: Redis | None = None,
    enabled: bool = True,
) -> QueryRewriter:
    testo = prompt or load_prompt("rewrite_system_v1")
    return QueryRewriter(llm, testo, enabled=enabled, cache=cache)
