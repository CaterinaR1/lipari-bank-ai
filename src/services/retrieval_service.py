# src/services/retrieval_service.py — la ricerca sui passaggi: vettori, lessico, o entrambi
import re
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import text as sql
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.acl import visible_to

SOGLIA_PREDEFINITA = 0.35  # da tarare sui propri documenti: non è un numero universale
RRF_K = 60  # la costante standard di Reciprocal Rank Fusion
SearchMode = Literal["vector", "hybrid"]


class RetrievalResult(BaseModel):
    chunk_id: str
    document_id: str
    content: str
    similarity: float


class RetrievalService:
    """La ricerca vettoriale e quella lessicale, fuse senza sommare punteggi di scale diverse."""

    SQL = sql(
        """
        SELECT id, document_id, content,
               1 - (embedding <=> CAST(:q AS vector)) AS similarity
        FROM document_chunks
        WHERE 1 - (embedding <=> CAST(:q AS vector)) >= :soglia
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
        """
    )

    SQL_LESSICALE = sql(
        """
        SELECT id, document_id, content
        FROM document_chunks
        WHERE to_tsvector('italian', content) @@ websearch_to_tsquery('italian', :q)
        ORDER BY ts_rank(
            to_tsvector('italian', content), websearch_to_tsquery('italian', :q)
        ) DESC
        LIMIT :k
        """
    )

        # le stesse query con UNA riga in più, dentro il WHERE e prima dell'ordinamento
    SQL_PER_RUOLO = sql(
        """
        SELECT id, document_id, content,
               1 - (embedding <=> CAST(:q AS vector)) AS similarity
        FROM document_chunks
        WHERE 1 - (embedding <=> CAST(:q AS vector)) >= :soglia
          AND visibility = ANY(:livelli)                     -- <- la riga
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
        """
    )

    SQL_LESSICALE_PER_RUOLO = sql(
        """
        SELECT id, document_id, content
        FROM document_chunks
        WHERE to_tsvector('italian', content) @@ websearch_to_tsquery('italian', :q)
          AND visibility = ANY(:livelli)                     -- <- la riga
        ORDER BY ts_rank(
            to_tsvector('italian', content), websearch_to_tsquery('italian', :q)
        ) DESC
        LIMIT :k
        """
    )



    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self,
        query_vec: list[float],
        top_k: int = 5,
        soglia: float = SOGLIA_PREDEFINITA,
        livelli: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """... (docstring com'è) ...

        Con `livelli=None` NON c'è filtro di visibilità: solo per ingestione e script.
        Da una richiesta HTTP si passano sempre i livelli del ruolo.
        """
        parametri: dict[str, object] = {"q": str(query_vec), "k": top_k, "soglia": soglia}
        if livelli is None:
            righe = await self.session.execute(self.SQL, parametri)
        else:
            righe = await self.session.execute(
                self.SQL_PER_RUOLO, parametri | {"livelli": livelli}
            )
        return [
            RetrievalResult(
                chunk_id=str(r.id),
                document_id=r.document_id,
                content=r.content,
                similarity=float(r.similarity),
            )
            for r in righe
        ]

    async def search_for_user(
        self,
        query_vec: list[float],
        role: str,
        top_k: int = 5,
        soglia: float = SOGLIA_PREDEFINITA,
    ) -> list[RetrievalResult]:
        """I passaggi più vicini FRA QUELLI che questo ruolo può vedere.

        Il filtro sui livelli sta DENTRO la query, non dopo: il database non deve
        nemmeno restituire i passaggi che questo ruolo non può vedere.
        """
        righe = await self.session.execute(
            self.SQL_PER_RUOLO,
            {"q": str(query_vec), "k": top_k, "soglia": soglia, "livelli": visible_to(role)},
        )
        return [
            RetrievalResult(
                chunk_id=str(r.id),
                document_id=r.document_id,
                content=r.content,
                similarity=float(r.similarity),
            )
            for r in righe
        ]

    async def search_lexical(
        self,
        query_text: str,
        top_k: int = 5,
        livelli: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """La ricerca per parole: trova i codici e le sigle che il vettore non avvicina.

        Il punteggio lessicale non viene esposto come `similarity`: non è un coseno e
        sommarlo a uno lo renderebbe un numero che non significa niente.

        Le parole sono unite con OR: una domanda in italiano contiene quasi sempre una
        parola che non compare nel passaggio giusto, e con AND quel passaggio sparirebbe.
        """
        # I numeri con separatore restano un token solo: "5.000" è così nell'indice,
        # mentre "5" e "000" separati non lo troverebbero.
        termini = re.findall(r"\d+(?:[.,]\d+)+|\w+", query_text)
        if not termini:
            return []
        query = " or ".join(termini)
        parametri: dict[str, object] = {"q": query, "k": top_k}
        if livelli is None:
            righe = await self.session.execute(self.SQL_LESSICALE, parametri)
        else:
            righe = await self.session.execute(
                self.SQL_LESSICALE_PER_RUOLO, parametri | {"livelli": livelli}
            )
        return [
            RetrievalResult(
                chunk_id=str(r.id),
                document_id=r.document_id,
                content=r.content,
                similarity=0.0,
            )
            for r in righe
        ]

    async def search_lexical_strict(
        self, query_text: str, top_k: int = 5, livelli: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """La ricerca per parole senza OR: tutti i termini nello stesso passaggio.

        È il segnale di precisione per importi e codici composti ("10.000 EUR"): un
        passaggio che contiene entrambi vale più di uno che ne contiene solo uno.
        """
        if not re.search(r"\w", query_text):
            return []
        parametri: dict[str, object] = {"q": query_text, "k": top_k}
        if livelli is None:
            righe = await self.session.execute(self.SQL_LESSICALE, parametri)
        else:
            righe = await self.session.execute(
                self.SQL_LESSICALE_PER_RUOLO, parametri | {"livelli": livelli}
            )
        return [
            RetrievalResult(
                chunk_id=str(r.id),
                document_id=r.document_id,
                content=r.content,
                similarity=0.0,
            )
            for r in righe
        ]

    async def search_hybrid(
        self,
        query_vec: list[float],
        query_text: str,
        top_k: int = 5,
        soglia: float = SOGLIA_PREDEFINITA,
        livelli: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Fonde i due elenchi con Reciprocal Rank Fusion.

        Si fondono i **ranghi**, non i punteggi: `1/(60 + posizione)` vale per liste di
        lunghezza diversa e non dipende dalla scala di cosine o di `ts_rank`. Sommare i
        punteggi grezzi farebbe vincere sempre la lista che, per caso, ha numeri più alti.
        """
        profondita = max(top_k * 10, 50)
        vettoriali = await self.search(query_vec, top_k=top_k * 3, soglia=soglia, livelli=livelli)
        lessicali = await self.search_lexical(query_text, top_k=profondita, livelli=livelli)
        stretti = await self.search_lexical_strict(query_text, top_k=profondita, livelli=livelli)

        # Il lessico largo non può tirare dentro un documento che né il vettore né la
        # ricerca stretta hanno trovato: altrimenti una domanda fuori corpus entra
        # comunque, agganciata a una parola comune come "conto".
        if not vettoriali and not stretti:
            return []
        documenti_ammessi = {r.document_id for r in vettoriali} | {
            r.document_id for r in stretti
        }
        lessicali = [r for r in lessicali if r.document_id in documenti_ammessi]

        punteggi: dict[str, float] = {}
        risultati: dict[str, RetrievalResult] = {}
        rango_lessicale: dict[str, int] = {}
        rango_stretto: dict[str, int] = {}
        for elenco in (vettoriali, lessicali, stretti):
            for posizione, passaggio in enumerate(elenco, start=1):
                risultati.setdefault(passaggio.chunk_id, passaggio)
                punteggi[passaggio.chunk_id] = punteggi.get(passaggio.chunk_id, 0.0) + (
                    1.0 / (RRF_K + posizione)
                )
                if elenco is lessicali:
                    rango_lessicale[passaggio.chunk_id] = posizione
                if elenco is stretti:
                    rango_stretto[passaggio.chunk_id] = posizione

        # I punteggi RRF sono discreti e i pareggi sono frequenti: a parità di punteggio
        # vince chi stava più in alto nella lista stretta, poi in quella lessicale.
        ordinati = sorted(
            punteggi,
            key=lambda chunk_id: (
                punteggi[chunk_id],
                -rango_stretto.get(chunk_id, profondita + 1),
                -rango_lessicale.get(chunk_id, profondita + 1),
                risultati[chunk_id].similarity,
            ),
            reverse=True,
        )
        return [risultati[chunk_id] for chunk_id in ordinati[:top_k]]
