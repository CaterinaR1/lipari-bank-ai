# src/llm/local_embedding_client.py — gli embedding senza rete: fastembed, ONNX, stesso modello
import asyncio
from functools import cache

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType

_registrati: set[str] = set()


def _registra(nome: str, dim: int) -> None:
    """I modelli non nativi si aggiungono a runtime, una volta per processo."""
    if nome in _registrati:
        return
    TextEmbedding.add_custom_model(
        model=nome,
        pooling=PoolingType.MEAN,  # E5 vuole la media dei token
        normalization=True,  # vettori unitari: il coseno è un prodotto scalare
        sources=ModelSource(hf=nome),
        dim=dim,
        model_file="onnx/model.onnx",
    )
    _registrati.add(nome)


@cache
def _modello(nome: str, dim: int) -> TextEmbedding:
    _registra(nome, dim)
    return TextEmbedding(model_name=nome)


class LocalEmbeddingClient:
    """Lo stesso contratto dell'embedder OpenAI, ma il modello gira in locale.

    E5 vuole `passage:` sui documenti e `query:` sulle domande: due gesti separati, altrimenti
    il confronto perde proprio la differenza fra ciò che si indicizza e ciò che si cerca.
    """

    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        modello = _modello(self.model, self.dim)
        # fastembed è sincrono e usa la CPU: fuori dal loop, o blocca tutte le richieste
        vettori = await asyncio.to_thread(lambda: list(modello.embed(texts)))
        return [[float(x) for x in vettore] for vettore in vettori]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed([f"passage: {testo}" for testo in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([f"query: {text}"]))[0]
