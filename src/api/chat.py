# src/api/chat.py — la chat, con la memoria
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.chat_service import ChatService

from src.db.session import get_db
from src.types.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/ai", tags=["Chat"])

# L'utente è finto: dal Giorno 6 arriva dal token, e questa riga cambia
UTENTE = "mbianchi"


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Manda un messaggio all'assistente",
        description="Conversazione a più turni, salvata nel database. «new» ne apre una."
)
async def chat(
    req: ChatRequest, session: Annotated[AsyncSession, Depends(get_db)]
) -> ChatResponse:
    return await ChatService(session).reply(UTENTE, req.session_id, req.message)
