# evals/ingest_fixtures.py — prepara l'indice e i dati minimi per la valutazione
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from src.db.models import Account, Customer
from src.db.session import AsyncSessionLocal
from src.llm.factory import get_embedder
from src.services.ingest_service import IngestService

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "docs"

CLIENTI = [
    ("C-10234", "Paolo Ferri", "mbianchi"),
    ("C-20417", "Anna Greco", "pgalli"),
]
CONTI = [
    ("IT60X0542811101000000123", "C-10234", "principale", "48200.00"),
    ("IT60X0542811101000000456", "C-10234", "risparmio", "1200.00"),
    ("IT60X0542811101000000789", "C-20417", "principale", "15300.00"),
]


def _visibility(path: Path) -> str:
    p = path.as_posix().lower()
    if "compliance_only" in p:
        return "compliance_only"
    if "risk_only" in p:
        return "risk_only"
    if "internal" in p:
        return "internal"
    return "public"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        if await session.scalar(select(Customer.id).limit(1)) is None:
            from decimal import Decimal

            session.add_all([Customer(id=c, full_name=n, operator=o) for c, n, o in CLIENTI])
            await session.flush()
            session.add_all(
                [
                    Account(id=i, customer_id=c, label=label, balance=Decimal(b))
                    for i, c, label, b in CONTI
                ]
            )
            await session.commit()

        embedder = get_embedder()
        ingest = IngestService(session, embedder)
        count = 0
        for path in sorted(DOCS.rglob("*.md")):
            doc_id = path.stem
            vis = _visibility(path)
            text = path.read_text(encoding="utf-8")
            n = await ingest.ingest(doc_id, text, {"path": path.as_posix()}, vis)
            count += n
            print(f"ingested {doc_id} ({vis}) -> {n} chunks")

    print(f"done: {count} chunks")


if __name__ == "__main__":
    asyncio.run(main())
