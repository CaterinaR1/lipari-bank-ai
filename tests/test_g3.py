# tests/test_g3.py — la memoria: quello che deve accadere, e quello che non deve
import operator
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import reduce

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from alembic import command
from scripts import seed_accounts
from src.db.models import Movement
from src.db.repos import AccountRepository, ChatRepository
from src.db.session import AsyncSessionLocal, engine
from src.main import app

PRINCIPALE, _, CONTO_DI_ANNA = (c[0] for c in seed_accounts.CONTI)


@pytest.fixture(autouse=True)
async def tabelle_vuote() -> AsyncIterator[None]:
    # Il pool si svuota prima e dopo ogni test: il TestClient dei test di ieri gira in un suo
    # event loop, e le connessioni restano nel pool legate al loop che le ha aperte. Prima, per
    # quelle che ha lasciato lui; dopo, per quelle di questo test, se il prossimo è suo.
    await engine.dispose()
    # CASCADE: le tabelle che arriveranno nei giorni dopo puntano a queste
    async with engine.begin() as c:
        await c.execute(
            text("TRUNCATE chat_messages, chat_sessions, movements, accounts, customers CASCADE")
        )
    yield
    await engine.dispose()


async def conta(tabella: str) -> int:
    async with AsyncSessionLocal() as s:
        return int((await s.execute(text(f"SELECT COUNT(*) FROM {tabella}"))).scalar_one())


def client(*, raise_app_exceptions: bool = True) -> AsyncClient:
    trasporto = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    return AsyncClient(transport=trasporto, base_url="http://test")


# ------------------------------------------------------------------ la conversazione
async def test_la_conversazione_sopravvive_al_riavvio():
    async with client() as c:
        r1 = await c.post("/api/ai/chat", json={"session_id": "new", "message": "Hello!"})
        sid = r1.json()["session_id"]
        r2 = await c.post("/api/ai/chat", json={"session_id": sid, "message": "Second message"})
    assert r1.status_code == r2.status_code == 200 and r2.json()["session_id"] == sid

    await engine.dispose()  # il «riavvio»: nessuna connessione del processo di prima
    nuovo = create_async_engine(engine.url.render_as_string(hide_password=False))
    async with nuovo.connect() as conn:
        ruoli = await conn.scalars(
            text("SELECT role FROM chat_messages WHERE session_id = :s ORDER BY created_at"),
            {"s": sid},
        )
        assert list(ruoli) == ["user", "assistant", "user", "assistant"]
    await nuovo.dispose()


async def test_la_conversazione_di_un_altro_e_404():
    async with AsyncSessionLocal() as s:
        altrui = await ChatRepository(s).create_session(user_id="pgalli")
        await s.commit()
    async with client() as c:
        r = await c.post("/api/ai/chat", json={"session_id": altrui.id, "message": "x"})
    assert r.status_code == 404 and await conta("chat_messages") == 0


async def test_un_errore_a_meta_non_lascia_niente(monkeypatch: pytest.MonkeyPatch):
    originale = ChatRepository.add_message
    chiamate = 0

    async def seconda_fallisce(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal chiamate
        chiamate += 1
        if chiamate == 2:
            raise RuntimeError("il processo muore fra le due scritture")
        return await originale(self, *args, **kwargs)

    monkeypatch.setattr(ChatRepository, "add_message", seconda_fallisce)
    async with client(raise_app_exceptions=False) as c:
        r = await c.post("/api/ai/chat", json={"session_id": "new", "message": "x"})
    assert r.status_code == 500
    assert await conta("chat_messages") == 0 and await conta("chat_sessions") == 0


async def test_venti_messaggi_due_query():
    async with AsyncSessionLocal() as s:
        repo = ChatRepository(s)
        chat = await repo.create_session(user_id="mbianchi")
        for i in range(20):
            await repo.add_message(chat.id, "user", f"messaggio {i}")
        await s.commit()

    query: list[str] = []

    def registra(*args: object) -> None:
        query.append(str(args[2]))

    event.listen(engine.sync_engine, "before_cursor_execute", registra)
    try:
        async with AsyncSessionLocal() as s:
            trovata = await ChatRepository(s).find_session(chat.id, "mbianchi")
            assert trovata is not None and len(trovata.messages) == 20
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registra)
    assert len(query) == 2  # la sessione, e i messaggi con un IN: non una query per messaggio


# ------------------------------------------------------------------ lo schema e i dati
def test_la_migration_riapplicata_non_rompe_niente():
    command.upgrade(Config("alembic.ini"), "head")  # già a head: non deve fare niente


async def test_il_seed_si_rilancia_senza_duplicare(capsys: pytest.CaptureFixture[str]):
    await seed_accounts.main()
    await seed_accounts.main()
    assert "nessuna azione" in capsys.readouterr().out
    assert (await conta("customers"), await conta("accounts"), await conta("movements")) == (
        2,
        3,
        len(seed_accounts.MOVIMENTI),
    )


def periodo() -> dict[str, str]:
    oggi = date.today()
    return {"date_from": str(oggi - timedelta(days=90)), "date_to": str(oggi)}


async def test_i_movimenti_arrivano_con_l_intestatario():
    await seed_accounts.main()
    async with client() as c:
        r = await c.get(f"/api/ai/accounts/{PRINCIPALE}/movements", params=periodo())
    attesi = [m for m in seed_accounts.MOVIMENTI if m[0] == PRINCIPALE]
    assert r.status_code == 200 and len(r.json()) == len(attesi)
    assert {m["owner"] for m in r.json()} == {"Paolo Ferri"}


async def test_il_totale_speso_torna_al_centesimo():
    await seed_accounts.main()
    async with client() as c:
        r = await c.get(f"/api/ai/accounts/{PRINCIPALE}/spending", params=periodo())
    uscite = [-a for i, _, _, a in seed_accounts.MOVIMENTI if i == PRINCIPALE and a < 0]
    assert Decimal(r.json()["total"]) == sum(uscite, Decimal("0"))
    assert reduce(operator.add, (float(u) for u in uscite)) != 20402.22


async def test_il_conto_di_un_altro_portafoglio_non_esiste():
    await seed_accounts.main()
    async with client() as c:
        r = await c.get(f"/api/ai/accounts/{CONTO_DI_ANNA}/spending", params=periodo())
    assert r.status_code == 404 and r.json()["error"] == "ACCOUNT_NOT_FOUND"
    assert "Anna" not in r.text  # nemmeno il nome dell'intestataria


async def test_un_periodo_rovesciato_e_422():
    async with client() as c:
        r = await c.get(
            f"/api/ai/accounts/{PRINCIPALE}/spending",
            params={"date_from": "2026-09-30", "date_to": "2026-09-01"},
        )
    assert r.status_code == 422 and r.json()["error"] == "INVALID_PERIOD"

# ------------------------------------------------------------------ l'estensione e il commit
async def saldo(iban: str) -> Decimal:
    async with AsyncSessionLocal() as s:
        sql = text("SELECT balance FROM accounts WHERE id = :i")
        return Decimal((await s.execute(sql, {"i": iban})).scalar_one())


NUOVO = {
    "booking_date": "2026-11-03",
    "description": "Commissione tenuta conto",
    "amount": "-12.50",
    }


async def test_un_movimento_aggiorna_il_saldo():
    await seed_accounts.main()
    prima = await saldo(PRINCIPALE)
    async with client() as c:
        r = await c.post(f"/api/ai/accounts/{PRINCIPALE}/movements", json=NUOVO)
    assert r.status_code == 201 and Decimal(r.json()["balance_after"]) == prima - Decimal("12.50")
    assert await saldo(PRINCIPALE) == prima - Decimal("12.50")


async def test_movimento_e_saldo_riescono_o_falliscono_insieme(monkeypatch: pytest.MonkeyPatch):
    await seed_accounts.main()
    saldo_prima, movimenti_prima = await saldo(PRINCIPALE), await conta("movements")

    async def salta(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("il saldo non si aggiorna")

    monkeypatch.setattr(AccountRepository, "adjust_balance", salta)
    async with client(raise_app_exceptions=False) as c:
        r = await c.post(f"/api/ai/accounts/{PRINCIPALE}/movements", json=NUOVO)
    assert r.status_code == 500
    assert await conta("movements") == movimenti_prima
    assert await saldo(PRINCIPALE) == saldo_prima


async def test_se_il_commit_fallisce_il_client_lo_vede(monkeypatch: pytest.MonkeyPatch):
    await seed_accounts.main()  # prima del patch: il seed usa lo stesso commit
    saldo_prima, movimenti_prima = await saldo(PRINCIPALE), await conta("movements")

    async def commit_che_cade(self) -> None:  # noqa: ANN001
        raise RuntimeError("la connessione cade al commit")

    monkeypatch.setattr(AsyncSession, "commit", commit_che_cade)
    async with client(raise_app_exceptions=False) as c:
        r = await c.post(f"/api/ai/accounts/{PRINCIPALE}/movements", json=NUOVO)
    assert r.status_code == 500 and r.json()["error"] == "INTERNAL_ERROR"  # non un 200
    assert await conta("movements") == movimenti_prima
    assert await saldo(PRINCIPALE) == saldo_prima

EXTRA = [
    ("Commissione bonifico", Decimal("-0.10")),
    ("Commissione bonifico", Decimal("-0.20")),
    ("Commissione carta", Decimal("-0.30")),
    ("Spesa con tre decimali", Decimal("-12.345")),
    ("Spesa con tre decimali", Decimal("-7.125")),
]


def al_centesimo(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def test_prova_del_centesimo_e_tre_decimali():
    await seed_accounts.main()
    async with AsyncSessionLocal() as s:
        s.add_all(
            Movement(
                account_id=PRINCIPALE, booking_date=date.today(), description=d, amount=a
            )
            for d, a in EXTRA
        )
        await s.commit()
    async with client() as c:
        r = await c.get(f"/api/ai/accounts/{PRINCIPALE}/spending", params=periodo())

    seed = sum(
        (-a for i, _, _, a in seed_accounts.MOVIMENTI if i == PRINCIPALE and a < 0), Decimal("0")
    )
    atteso = seed + sum((-al_centesimo(a) for _, a in EXTRA), Decimal("0"))
    esatto = seed + sum((-a for _, a in EXTRA), Decimal("0"))
    assert Decimal(r.json()["total"]) == atteso
    assert atteso != esatto  # 12.345 e 7.125 sono diventati 12.35 e 7.13, senza dire niente
