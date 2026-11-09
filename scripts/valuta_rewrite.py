# scripts/valuta_rewrite.py — il delta del riscrittore, senza e con la storia
import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from src.db.session import AsyncSessionLocal, engine
from src.llm.embedding_client import Embedder
from src.llm.factory import get_embedder, get_llm_provider
from src.llm.prompt import load_prompt
from src.llm.rewriter import QueryRewriter
from src.services.retrieval_service import SOGLIA_PREDEFINITA, RetrievalService

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REWRITE = Path("data/eval/domande_g6_rewrite.jsonl")
STORIA = Path("data/eval/domande_g6_storia.jsonl")


class DomandaRiscritta(BaseModel):
    id: str
    question: str
    rewritten: str
    gold_document: str
    gold_phrase: str


class DomandaConStoria(BaseModel):
    id: str
    history: list[str]
    followup: str
    rewritten_senza_storia: str
    rewritten_con_storia: str
    gold_document: str
    gold_phrase: str


@dataclass
class Esito:
    doc5: bool
    chunk5: bool
    doc1: bool
    mrr: float


@dataclass
class Aggregato:
    doc5: int = 0
    chunk5: int = 0
    doc1: int = 0
    mrr: float = 0.0
    n: int = 0

    def aggiungi(self, esito: Esito) -> None:
        self.doc5 += int(esito.doc5)
        self.chunk5 += int(esito.chunk5)
        self.doc1 += int(esito.doc1)
        self.mrr += esito.mrr
        self.n += 1

    def riga(self, etichetta: str, k: int) -> str:
        n = self.n or 1
        return (
            f"{etichetta:<22} doc@{k} {self.doc5}/{self.n} = {self.doc5 / n:.3f}   "
            f"chunk@{k} {self.chunk5}/{self.n} = {self.chunk5 / n:.3f}   "
            f"doc@1 {self.doc1}/{self.n} = {self.doc1 / n:.3f}   "
            f"MRR {self.mrr / n:.3f}"
        )

    def delta(self, altro: "Aggregato", k: int) -> str:
        return (
            f"{'delta':<22} doc@{k} {self.doc5 - altro.doc5:+d} "
            f"({(self.doc5 - altro.doc5) / (self.n or 1):+.3f})   "
            f"chunk@{k} {self.chunk5 - altro.chunk5:+d} "
            f"({(self.chunk5 - altro.chunk5) / (self.n or 1):+.3f})   "
            f"doc@1 {self.doc1 - altro.doc1:+d}   "
            f"MRR {(self.mrr - altro.mrr) / (self.n or 1):+.3f}"
        )


async def _leggi[Modello: BaseModel](percorso: Path, modello: type[Modello]) -> list[Modello]:
    testo = await asyncio.to_thread(percorso.read_text, encoding="utf-8")
    return [
        modello.model_validate_json(riga) for riga in testo.splitlines() if riga.strip()
    ]


async def _misura(
    servizio: RetrievalService,
    embedder: Embedder,
    testo: str,
    gold_document: str,
    gold_phrase: str,
    k: int,
    soglia: float,
) -> Esito:
    vettore = await embedder.embed_query(testo)
    risultati = await servizio.search(vettore, top_k=k, soglia=soglia)
    documenti = [r.document_id for r in risultati]
    doc5 = gold_document in documenti
    chunk5 = any(gold_phrase in r.content for r in risultati)
    doc1 = bool(documenti) and documenti[0] == gold_document
    mrr = 1.0 / (documenti.index(gold_document) + 1) if doc5 else 0.0
    return Esito(doc5=doc5, chunk5=chunk5, doc1=doc1, mrr=mrr)


async def _valuta_rewrite(percorso: Path, k: int, soglia: float) -> None:
    domande = await _leggi(percorso, DomandaRiscritta)
    embedder = get_embedder()
    senza = Aggregato()
    con = Aggregato()
    print(f"riscrittura senza storia: {len(domande)} domande, k={k}, soglia={soglia}\n")
    async with AsyncSessionLocal() as session:
        servizio = RetrievalService(session)
        for domanda in domande:
            esito_senza = await _misura(
                servizio,
                embedder,
                domanda.question,
                domanda.gold_document,
                domanda.gold_phrase,
                k,
                soglia,
            )
            esito_con = await _misura(
                servizio,
                embedder,
                domanda.rewritten,
                domanda.gold_document,
                domanda.gold_phrase,
                k,
                soglia,
            )
            senza.aggiungi(esito_senza)
            con.aggiungi(esito_con)
            print(
                f"{domanda.id}  senza={'OK' if esito_senza.doc5 else 'NO'} "
                f"con={'OK' if esito_con.doc5 else 'NO'}  {domanda.rewritten}"
            )
    print("\n--- totale ---")
    print(senza.riga("senza riscrittore", k))
    print(con.riga("con riscrittore", k))
    print(con.delta(senza, k))


async def _valuta_storia(percorso: Path, k: int, soglia: float) -> None:
    domande = await _leggi(percorso, DomandaConStoria)
    embedder = get_embedder()
    grezza = Aggregato()
    senza = Aggregato()
    con = Aggregato()
    print(f"domande che dipendono dalla precedente: {len(domande)}, k={k}, soglia={soglia}\n")
    async with AsyncSessionLocal() as session:
        servizio = RetrievalService(session)
        for domanda in domande:
            esito_grezzo = await _misura(
                servizio,
                embedder,
                domanda.followup,
                domanda.gold_document,
                domanda.gold_phrase,
                k,
                soglia,
            )
            esito_senza = await _misura(
                servizio,
                embedder,
                domanda.rewritten_senza_storia,
                domanda.gold_document,
                domanda.gold_phrase,
                k,
                soglia,
            )
            esito_con = await _misura(
                servizio,
                embedder,
                domanda.rewritten_con_storia,
                domanda.gold_document,
                domanda.gold_phrase,
                k,
                soglia,
            )
            grezza.aggiungi(esito_grezzo)
            senza.aggiungi(esito_senza)
            con.aggiungi(esito_con)
            print(
                f"{domanda.id}  grezza={'OK' if esito_grezzo.doc5 else 'NO'} "
                f"senza_storia={'OK' if esito_senza.doc5 else 'NO'} "
                f"con_storia={'OK' if esito_con.doc5 else 'NO'}  {domanda.rewritten_con_storia}"
            )
    print("\n--- totale ---")
    print(grezza.riga("followup grezza", k))
    print(senza.riga("senza storia", k))
    print(con.riga("con storia", k))
    print(con.delta(senza, k))


async def _rigenera(percorso: Path, storia: bool) -> None:
    riscrittore = QueryRewriter(get_llm_provider(), load_prompt("rewrite_system_v1"))
    if storia:
        for domanda in await _leggi(percorso, DomandaConStoria):
            domanda.rewritten_senza_storia = await riscrittore.rewrite(domanda.followup)
            domanda.rewritten_con_storia = await riscrittore.rewrite(
                domanda.followup, domanda.history
            )
            print(domanda.model_dump_json())
    else:
        for riscritta in await _leggi(percorso, DomandaRiscritta):
            riscritta.rewritten = await riscrittore.rewrite(riscritta.question)
            print(riscritta.model_dump_json())


async def main() -> None:
    parser = argparse.ArgumentParser(description="Misura il delta del riscrittore")
    parser.add_argument("--storia", action="store_true", help="usa le cinque domande dipendenti")
    parser.add_argument("--file", default=None, help="dataset JSONL alternativo")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--soglia", type=float, default=SOGLIA_PREDEFINITA)
    parser.add_argument(
        "--rigenera",
        action="store_true",
        help="rigenera le riscritture col modello e stampa il JSONL (non sovrascrive)",
    )
    args = parser.parse_args()
    percorso = Path(args.file) if args.file else (STORIA if args.storia else REWRITE)
    try:
        if args.rigenera:
            await _rigenera(percorso, args.storia)
        elif args.storia:
            await _valuta_storia(percorso, args.k, args.soglia)
        else:
            await _valuta_rewrite(percorso, args.k, args.soglia)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
