# src/api/chat.py — la chat, per ora un'eco
from datetime import UTC, datetime

from fastapi import APIRouter

from src.types.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/ai", tags=["Chat"])


@router.post(
    "/chat",  # relativo al prefix: l'URL è /api/ai/chat
    response_model=ChatResponse,
    summary="Manda un messaggio all'assistente",
    description="Conversazione a più turni. Dal Giorno 4 risponde un modello vero.",
)
async def chat(req: ChatRequest) -> ChatResponse:
    return ChatResponse(
        session_id=req.session_id,
        reply=f"Echo: {req.message}",
        tokens_used=10,
        cost_eur=0.0001,
        model_used="dummy",
        created_at=datetime.now(UTC),
    )
