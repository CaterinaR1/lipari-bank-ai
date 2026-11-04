# src/llm/stima.py — quanto è costata una risposta interrotta: una stima, e dichiarata tale
from decimal import Decimal

from src.llm.anthropic_provider import PRICING as PREZZI_ANTHROPIC
from src.llm.openai_provider import PRICING as PREZZI_OPENAI
from src.llm.types import Message

PREZZI = {**PREZZI_OPENAI, **PREZZI_ANTHROPIC}


def token_stimati(testo: str) -> int:
    """Circa quattro caratteri per token: un'approssimazione, non una misura."""
    return len(testo) // 4 + 1


def costo_stimato(modello: str, messaggi: list[Message], parziale: str) -> tuple[int, Decimal]:
    entrata = sum(token_stimati(m.content) for m in messaggi)
    uscita = token_stimati(parziale)
    prezzo_in, prezzo_out = PREZZI.get(modello, (Decimal("0"), Decimal("0")))
    return entrata + uscita, (entrata * prezzo_in + uscita * prezzo_out) / 1000
