# tests/test_g5_est.py — l'estensione: il lessico entra solo se il documento è plausibile
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from src.db.session import AsyncSessionLocal, engine
from src.services.ingest_service import IngestService
from src.services.retrieval_service import RetrievalService
from tests.finti import embedder_finto, vettore


@pytest.fixture(autouse=True)
async def indice_vuoto() -> AsyncIterator[None]:
    await engine.dispose()
    async with engine.begin() as c:
        await c.execute(text("TRUNCATE document_chunks"))
    yield


async def test_ibrida_usa_il_lessico_solo_quando_il_documento_e_plausibile():
    async with AsyncSessionLocal() as s:
        servizio_ingest = IngestService(s, embedder_finto())
        await servizio_ingest.ingest(
            "doc_soglia", "La soglia è 15.000 EUR per singola operazione.", {}
        )
        await servizio_ingest.ingest("doc_conto", "Il conto corrente ha un canone mensile.", {})

    async with AsyncSessionLocal() as s:
        servizio = RetrievalService(s)

        # il vettore, con una soglia alta, non vede l'importo; il lessico sì
        vettoriale = await servizio.search(vettore("15.000 EUR"), soglia=0.99)
        ibrida = await servizio.search_hybrid(vettore("15.000 EUR"), "15.000 EUR", soglia=0.99)
        assert vettoriale == []
        assert [r.document_id for r in ibrida] == ["doc_soglia"]

        # "conto" basta al lessico largo, ma non a quello stretto né al vettore:
        # la fusione non deve inventare un documento che nessuno dei due ha trovato
        assert await servizio.search(vettore("mutuo conto"), soglia=0.99) == []
        assert await servizio.search_lexical("mutuo conto")
        assert await servizio.search_lexical_strict("mutuo conto") == []
        ibrida_vaga = await servizio.search_hybrid(
            vettore("mutuo conto"), "mutuo conto", soglia=0.99
        )
        assert ibrida_vaga == []
