# scripts/ingest_docs.py — i documenti di data/docs nell'indice, senza passare dal server
import argparse
import asyncio
from pathlib import Path

from src.db.session import AsyncSessionLocal, engine
from src.llm.factory import get_embedder
from src.services.ingest_service import IngestService


async def ingerisci(cartella: Path) -> None:
    percorsi = await asyncio.to_thread(lambda: sorted(cartella.glob("*.md")))
    if not percorsi:
        print(f"nessun documento in {cartella}")
        return
    embedder = get_embedder()
    for path in percorsi:
        testo = await asyncio.to_thread(path.read_text, encoding="utf-8")
        async with AsyncSessionLocal() as session:
            quanti = await IngestService(session, embedder).ingest(
                path.stem,
                testo,
                {"source": str(path), "title": path.stem.replace("_", " ")},
            )
        print(f"{path.name}: {quanti} passaggi")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Indicizza i documenti Markdown della banca")
    parser.add_argument(
        "--dir", default="data/docs", help="cartella dei documenti (default: data/docs)"
    )
    args = parser.parse_args()
    try:
        await ingerisci(Path(args.dir))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
