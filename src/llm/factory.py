# src/llm/factory.py - typed redis arg
from functools import cache

import instructor
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from src.config import settings
from src.exceptions import AppError
from src.llm.anthropic_provider import AnthropicProvider
from src.llm.client import LLMProvider
from src.llm.embedding_client import Embedder, EmbeddingClient
from src.llm.embeddings import CachedEmbedder
from src.llm.local_embedding_client import LocalEmbeddingClient
from src.llm.openai_provider import OpenAIProvider
from src.llm.prompt import load_prompt
from src.llm.rewriter import QueryRewriter


def _chiave(valore: str, nome: str) -> str:
    if not valore:
        raise AppError(503, "LLM_NOT_CONFIGURED", f"Manca {nome}: il modello non e configurato")
    return valore


@cache
def _openai() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_chiave(settings.openai_api_key, "OPENAI_API_KEY"),
        base_url=settings.openai_base_url or None,
        timeout=20.0,
        max_retries=2,
    )


@cache
def _anthropic() -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=_chiave(settings.anthropic_api_key, "ANTHROPIC_API_KEY"),
        timeout=20.0,
        max_retries=2,
    )


def get_llm_provider() -> LLMProvider:
    modello = settings.default_model
    if modello.startswith("claude"):
        return AnthropicProvider(_anthropic(), modello)
    if modello.startswith("gpt") or settings.openai_base_url:
        return OpenAIProvider(_openai(), modello)
    raise ValueError(f"Modello sconosciuto: {modello}")


def get_openai() -> AsyncOpenAI:
    return _openai()


@cache
def get_instructor() -> instructor.AsyncInstructor:
    return instructor.from_openai(_openai())


@cache
def _openai_embedding() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=_chiave(settings.embedding_api_key, "EMBEDDING_API_KEY"),
        timeout=20.0,
        max_retries=2,
    )


@cache
def get_embedder() -> Embedder:
    """Embedder per DI/test; usa Redis se configurato (best-effort)."""
    from src.cache import get_redis

    redis = get_redis()
    if settings.embedding_backend == "local":
        base: Embedder = LocalEmbeddingClient(settings.embedding_model, settings.embedding_dim)
    else:
        base = EmbeddingClient(_openai_embedding(), settings.embedding_model)
    if redis is None:
        return base
    return CachedEmbedder(
        base,
        redis,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
    )


@cache
def get_rewriter() -> QueryRewriter:
    from src.cache import get_redis

    return QueryRewriter(get_llm_provider(), load_prompt("rewrite_system_v1"), cache=get_redis())
