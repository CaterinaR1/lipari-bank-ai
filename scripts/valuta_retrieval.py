# scripts/valuta_retrieval.py — la linea di partenza: il documento giusto entra nei primi k?
import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from src.db.session import AsyncSessionLocal, engine
from src.llm.factory import get_embedder
from src.services.retrieval_service import SOGLIA_PREDEFINITA, RetrievalService, SearchMode

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def valuta(percorso: Path, mode: SearchMode, k: int, soglia: float) -> None:
    testo = await asyncio.to_thread(percorso.read_text, encoding="utf-8")
    domande: list[dict[str, Any]] = [
        json.loads(riga) for riga in testo.splitlines() if riga.strip()
    ]
    embedder = get_embedder()
    positivi = [d for d in domande if d["answerable"]]
    negativi = [d for d in domande if not d["answerable"]]
    colpi_documento = 0
    colpi_passaggio = 0
    colpi_documento_primo = 0
    somma_inversi_rango = 0.0
    negativi_con_passaggi = 0
    similarita_positive: list[float] = []
    similarita_negative: list[float] = []

    print(
        f"modalità: {mode}   k: {k}   soglia: {soglia}   "
        f"domande: {len(positivi)} positive, {len(negativi)} negative\n"
    )
    async with AsyncSessionLocal() as session:
        servizio = RetrievalService(session)
        for domanda in domande:
            vettore = await embedder.embed_query(domanda["question"])
            if mode == "hybrid":
                risultati = await servizio.search_hybrid(
                    vettore, domanda["question"], top_k=k, soglia=soglia
                )
            else:
                risultati = await servizio.search(vettore, top_k=k, soglia=soglia)
            grezzi = await servizio.search(vettore, top_k=1, soglia=-1.0)
            top1 = grezzi[0].similarity if grezzi else 0.0

            documenti = [r.document_id for r in risultati]
            if domanda["answerable"]:
                colpo_doc = domanda["gold_document"] in documenti
                colpo_chunk = any(
                    domanda["gold_phrase"] in r.content for r in risultati
                )
                colpi_documento += int(colpo_doc)
                colpi_passaggio += int(colpo_chunk)
                primo_giusto = bool(documenti) and documenti[0] == domanda["gold_document"]
                colpi_documento_primo += int(primo_giusto)
                if domanda["gold_document"] in documenti:
                    somma_inversi_rango += 1.0 / (documenti.index(domanda["gold_document"]) + 1)
                similarita_positive.append(top1)
                print(
                    f"{domanda['id']}  doc={'OK ' if colpo_doc else 'NO '} "
                    f"chunk={'OK ' if colpo_chunk else 'NO '} top1={top1:.3f}  {documenti}"
                )
            else:
                con_passaggi = bool(risultati)
                negativi_con_passaggi += int(con_passaggi)
                similarita_negative.append(top1)
                print(
                    f"{domanda['id']}  negativa  passaggi={len(risultati)} "
                    f"top1={top1:.3f}  {documenti}"
                )

    n_pos = len(positivi) or 1
    n_neg = len(negativi) or 1
    print("\n--- totale ---")
    print(
        f"hit-rate documento@{k}: {colpi_documento}/{len(positivi)} "
        f"= {colpi_documento / n_pos:.2f}"
    )
    print(
        f"hit-rate documento@1:    {colpi_documento_primo}/{len(positivi)} "
        f"= {colpi_documento_primo / n_pos:.2f}"
    )
    print(f"MRR documento:           {somma_inversi_rango / n_pos:.3f}")
    print(
        f"hit-rate passaggio@{k}:  {colpi_passaggio}/{len(positivi)} "
        f"= {colpi_passaggio / n_pos:.2f}"
    )
    print(
        f"negative con almeno un passaggio: {negativi_con_passaggi}/{len(negativi)} "
        f"= {negativi_con_passaggi / n_neg:.2f}"
    )
    if similarita_positive:
        print(
            "top1 coseno positivi: "
            f"media {statistics.mean(similarita_positive):.3f}, "
            f"min {min(similarita_positive):.3f}, max {max(similarita_positive):.3f}"
        )
    if similarita_negative:
        print(
            "top1 coseno negative: "
            f"media {statistics.mean(similarita_negative):.3f}, "
            f"min {min(similarita_negative):.3f}, max {max(similarita_negative):.3f}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Misura il recupero sulle domande di valutazione")
    parser.add_argument("--mode", choices=["vector", "hybrid"], default="vector")
    parser.add_argument("--file", default="data/eval/domande_g5.jsonl")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--soglia", type=float, default=SOGLIA_PREDEFINITA)
    args = parser.parse_args()
    try:
        await valuta(Path(args.file), args.mode, args.k, args.soglia)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
