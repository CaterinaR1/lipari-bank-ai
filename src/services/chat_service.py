# src/services/chat_service.py — la logica, e il punto in cui finisce la transazione
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repos import ChatRepository
from src.exceptions import ChatSessionNotFoundError
from src.types.chat import ChatResponse


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.chats = ChatRepository(session)

    async def reply(self, user_id: str, session_id: str, message: str) -> ChatResponse:
        if session_id == "new":
            chat = await self.chats.create_session(user_id)
        else:
            trovata = await self.chats.find_session(session_id, user_id)
            if trovata is None:  # anche se esiste ed è di un altro: stessa risposta
                raise ChatSessionNotFoundError(session_id)
            chat = trovata

        await self.chats.add_message(chat.id, "user", message)
        risposta = f"Echo: {message}"  # dal Giorno 4 risponde un modello vero
        creato = await self.chats.add_message(chat.id, "assistant", risposta)

        # Un solo commit, alla fine: se qualcosa solleva prima, la sessione si chiude senza
        # commit e non resta né la conversazione né mezza risposta.
        await self.session.commit()
        return ChatResponse(
            session_id=chat.id,
            reply=risposta,
            tokens_used=10,
            cost_eur=0.0001,
            model_used="dummy",
            created_at=creato.created_at,
        )
