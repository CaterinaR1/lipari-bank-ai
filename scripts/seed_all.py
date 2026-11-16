# scripts/seed_all.py - seed idempotente (utenti, conti, indice)
import asyncio
import os
from pathlib import Path

from sqlalchemy import func, select

from src.db.models import AppUser, Customer, DocumentChunk
from src.db.session import AsyncSessionLocal


async def seed_utenti() -> None:
    try:
        from scripts.seed_users import main as seed_users_main
    except Exception:
        seed_users_main = None  # type: ignore[assignment]
    if seed_users_main is not None:
        await seed_users_main()
        return
    from src.auth.passwords import hash_password

    utenti = [
        ("mbianchi", "Marco Bianchi", "operator"),
        ("grossi", "Giulia Rossi", "compliance_lead"),
        ("lverdi", "Lucia Verdi", "risk_lead"),
    ]
    async with AsyncSessionLocal() as session:
        for username, full_name, role in utenti:
            if await session.scalar(select(AppUser).where(AppUser.username == username)):
                continue
            session.add(
                AppUser(
                    username=username,
                    full_name=full_name,
                    password_hash=hash_password("bootcamp"),
                    role=role,
                )
            )
        await session.commit()


async def seed_conti() -> None:
    async with AsyncSessionLocal() as session:
        if await session.scalar(select(Customer.id).limit(1)) is not None:
            print("Conti/clienti gia presenti")
            return
    from scripts.seed_accounts import main as seed_accounts_main

    await seed_accounts_main()


def _visibility(path: Path, docs_dir: Path) -> str:
    rel = path.relative_to(docs_dir)
    if rel.parts and rel.parts[0] in {"internal", "risk_only", "compliance_only"}:
        return rel.parts[0]
    return "public"


async def seed_indice() -> None:
    async with AsyncSessionLocal() as session:
        presenti = await session.scalar(select(func.count()).select_from(DocumentChunk))
        if (presenti or 0) > 0 and os.environ.get("SEED_REINDEX") != "1":
            print(f"Indice gia presente ({presenti} chunk): skip")
            return

    try:
        from src.config import settings
        from src.llm.factory import get_embedder
        from src.services.ingest_service import IngestService

        if settings.embedding_backend == "openai" and not settings.embedding_api_key:
            print("Seed indice: EMBEDDING_API_KEY mancante, skip")
            return
        embedder = get_embedder(None)
    except Exception as e:
        print(f"Seed indice: embedder non disponibile ({e}), skip")
        return

    docs_dir = Path("data/docs")
    if not await asyncio.to_thread(docs_dir.exists):
        print("Seed indice: data/docs mancante, skip")
        return
    paths = await asyncio.to_thread(lambda: sorted(docs_dir.rglob("*.md")))
    async with AsyncSessionLocal() as session:
        ingest = IngestService(session, embedder)
        totale = 0
        for path in paths:
            contenuto = await asyncio.to_thread(path.read_text, encoding="utf-8")
            vis = _visibility(path, docs_dir)
            try:
                n = await ingest.ingest(path.stem, contenuto, {"source": str(path)}, vis)
                totale += n
                print(f"ingested {path.name} [{vis}] -> {n}")
            except Exception as e:
                print(f"ingest skip {path.name}: {e}")
        print(f"Indice: {totale} chunk")


async def main() -> None:
    await seed_utenti()
    await seed_conti()
    await seed_indice()


if __name__ == "__main__":
    asyncio.run(main())
