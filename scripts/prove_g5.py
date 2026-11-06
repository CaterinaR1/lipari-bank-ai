# scripts/prove_g5.py — le quattro prove del cancello, sull'indice vero e con il modello vero
import asyncio
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

from src.config import settings
from src.db.models import DocumentChunk
from src.db.session import AsyncSessionLocal, engine
from src.llm.embedding_client import Embedder
from src.llm.factory import get_embedder, get_llm_provider
from src.llm.prompt import load_prompt
from src.services.ingest_service import IngestService
from src.services.rag_service import RIFIUTO, RAGService
from src.services.retrieval_service import RetrievalService
from src.types.advice import AdviceRequest

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COMMISSIONI = Path("data/docs/commissioni_bonifico.md").read_text(encoding="utf-8")
PAGINA = """# Nota operativa 99/2026

La procedura PROVA2026 richiede la firma del responsabile di filiale e la conservazione del modulo
per dieci anni. Il codice PROVA2026 va inserito nell'area riservata prima dell'invio.
"""


async def conta(document_id: str) -> int:
    async with AsyncSessionLocal() as session:
        quanti = await session.scalar(
            select(func.count()).where(DocumentChunk.document_id == document_id)
        )
        return int(quanti or 0)


async def ingerisci(document_id: str, testo: str, embedder: Embedder) -> int:
    async with AsyncSessionLocal() as session:
        return await IngestService(session, embedder).ingest(
            document_id, testo, {"fonte": "prova"}
        )


async def rimuovi(document_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await session.commit()


async def _prove() -> None:
    embedder = get_embedder()
    llm = get_llm_provider()
    esiti: list[tuple[str, bool]] = []

    async with AsyncSessionLocal() as session:
        rag = RAGService(
            RetrievalService(session),
            embedder,
            llm,
            load_prompt("advice_system_v1"),
            mode=settings.retrieval_mode,
        )

        # 1. fuori corpus: rifiuto, non una citazione che non c'entra
        fuori = await rag.advise(
            AdviceRequest(
                question="Qual è il tasso del mutuo agevolato per giovani coppie sotto i 35 anni?"
            )
        )
        ok = (
            fuori.answer == RIFIUTO
            and not fuori.citations
            and fuori.tokens_used == 0
            and fuori.cost_eur == 0.0
        )
        esiti.append(("1. domanda fuori corpus → rifiuto senza modello", ok))
        print(
            f"[{'PASS' if ok else 'FAIL'}] fuori corpus: {fuori.answer[:90]!r} "
            f"({fuori.tokens_used} token, costo {fuori.cost_eur})"
        )

        # 2. lo stesso documento due volte: le citazioni non raddoppiano
        primo = await ingerisci("commissioni_bonifico", COMMISSIONI, embedder)
        secondo = await ingerisci("commissioni_bonifico", COMMISSIONI, embedder)
        doppia = await rag.advise(
            AdviceRequest(question="Quanto costa il bonifico istantaneo SEPA?")
        )
        coppie = [(c.document_id, c.excerpt) for c in doppia.citations]
        ok = primo == secondo and len(coppie) == len(set(coppie)) and bool(coppie)
        esiti.append(("2. doppio ingest → citazioni non duplicate", ok))
        print(f"[{'PASS' if ok else 'FAIL'}] doppio ingest: {primo} -> {secondo}, "
              f"{len(coppie)} citazioni, {len(set(coppie))} distinte")

        # 3. pagina ripetuta: nessuna citazione identica
        try:
            una = await ingerisci("pagina_ripetuta", PAGINA, embedder)
            due = await ingerisci("pagina_ripetuta", PAGINA + "\n\n" + PAGINA, embedder)
            ripetuta = await rag.advise(
                AdviceRequest(question="Cosa richiede la procedura PROVA2026?")
            )
            coppie = [(c.document_id, c.excerpt) for c in ripetuta.citations]
            ok = una == due and len(coppie) == len(set(coppie)) and bool(coppie)
            esiti.append(("3. pagina ripetuta → nessuna citazione identica", ok))
            print(f"[{'PASS' if ok else 'FAIL'}] pagina ripetuta: {una} -> {due}, "
                  f"{len(coppie)} citazioni: {ripetuta.answer[:90]!r}")
        finally:
            await rimuovi("pagina_ripetuta")

        # 4. domanda vaga: che cosa recupera davvero
        vaga = "bonifico estero"
        vettore = await embedder.embed_query(vaga)
        servizio = RetrievalService(session)
        vettoriali = await servizio.search(vettore)
        ibridi = await servizio.search_hybrid(vettore, vaga)
        risposta = await rag.advise(AdviceRequest(question=vaga))
        print(f"[INFO] domanda vaga {vaga!r}")
        print(f"       vettoriale: {[(p.document_id, round(p.similarity, 3)) for p in vettoriali]}")
        print(f"       ibrido:     {[(p.document_id, round(p.similarity, 3)) for p in ibridi]}")
        print(f"       risposta:   {risposta.answer[:110]!r} ({len(risposta.citations)} citazioni)")
        ok = bool(vettoriali) and bool(ibridi) and bool(risposta.citations)
        esiti.append(("4. domanda vaga → passaggi e citazioni", ok))

    print("\n--- esito ---")
    for nome, ok in esiti:
        print(f"{'PASS' if ok else 'FAIL'}  {nome}")


async def main() -> None:
    try:
        await _prove()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
