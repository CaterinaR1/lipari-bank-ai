# src/llm/embedding_client.py — i vettori, dallo stesso modello per documenti e domande
from typing import Protocol

import openai
from openai import AsyncOpenAI

from src.exceptions import LLMProviderError


class Embedder(Protocol):
    """Quello che serve a chi indicizza e a chi cerca: due gesti, non un solo metodo.

    I due gesti sono separati perché alcuni modelli (E5) vogliono prefissi diversi per il
    documento e per la domanda; chi usa l'embedder non deve sapere quale modello c'è sotto.
    """

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class EmbeddingClient:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client  # lo stesso della factory: un pool di connessioni per processo
        self.model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """I vettori di più testi in una chiamata, nello stesso ordine dei testi."""
        try:
            response = await self.client.embeddings.create(model=self.model, input=texts)
        except openai.APIError as e:  # come la chat: un guasto del fornitore è un 502, non un bug
            raise LLMProviderError("openai", str(e)) from e
        return [item.embedding for item in response.data]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]
