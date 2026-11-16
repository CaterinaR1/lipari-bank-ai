# src/api/advice.py - advisor con cache Redis opzionale
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.deps import UserContext, get_current_user, require_role
from src.auth.tokens import decode_token
from src.cache import get_redis
from src.config import settings
from src.db.repos import ChatRepository
from src.db.session import get_db
from src.llm.client import LLMProvider
from src.llm.embedding_client import Embedder
from src.llm.factory import get_embedder, get_llm_provider, get_rewriter
from src.llm.prompt import load_prompt
from src.llm.rewriter import QueryRewriter
from src.observability.cost_tracker import CostTracker
from src.observability.ledger import CostLedger
from src.services.ingest_service import IngestService
from src.services.rag_service import RAGService
from src.services.retrieval_service import RetrievalService
from src.types.advice import AdviceRequest, AdviceResponse, IngestRequest, IngestResponse

router = APIRouter(prefix="/api/ai", tags=["Advice"])
PROMPT = load_prompt("advice_system_v1")


def per_utente(request: Request) -> str:
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    try:
        return str(decode_token(token)["sub"])
    except Exception:
        return get_remote_address(request)


limiter = Limiter(
    key_func=per_utente,
    storage_uri=settings.redis_url or "memory://",
    in_memory_fallback_enabled=True,
)

__all__ = [
    "advice",
    "get_embedder",
    "get_ingest_service",
    "get_rag_service",
    "get_rewriter",
    "ingest",
    "limiter",
    "router",
]


def get_rag_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
    rewriter: Annotated[QueryRewriter, Depends(get_rewriter)],
) -> RAGService:
    return RAGService(
        RetrievalService(session),
        embedder,
        llm,
        rewriter,
        PROMPT,
        mode=settings.retrieval_mode,
        cache=get_redis(),
    )


def get_ingest_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> IngestService:
    return IngestService(session, embedder, cache=get_redis())


@router.post("/advice", response_model=AdviceResponse)
@limiter.limit("15/minute")
async def advice(
    request: Request,
    req: AdviceRequest,
    user: Annotated[UserContext, Depends(get_current_user)],
    service: Annotated[RAGService, Depends(get_rag_service)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AdviceResponse:
    repo = ChatRepository(session)
    await CostTracker(repo, settings.daily_budget_eur).verifica()
    esito = await service.advise(req.question, user, req.history)
    CostLedger(session).aggiungi(
        endpoint="advice",
        username=user.username,
        model=esito.model or settings.default_model,
        tokens=esito.tokens_used,
        cost_eur=Decimal(str(esito.cost_eur)),
    )
    await session.commit()
    return esito


@router.post("/documents/ingest", response_model=IngestResponse)
async def ingest(
    req: IngestRequest,
    user: Annotated[UserContext, Depends(require_role("compliance_lead", "admin"))],
    service: Annotated[IngestService, Depends(get_ingest_service)],
) -> IngestResponse:
    quanti = await service.ingest(req.document_id, req.content, req.metadata, req.visibility)
    return IngestResponse(chunk_count=quanti, embedding_dim=settings.embedding_dim)
