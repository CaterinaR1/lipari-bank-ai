# tests/unit/test_g7.py
import logging
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import omit
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.deps import Deps, get_deps
from src.agents.loop import BUDGET_PER_RUN, run_agent
from src.agents.registry import Tool, impronta
from src.agents.tools import (
    NON_DISPONIBILE,
    ClienteArgs,
    RicercaArgs,
    SaldoArgs,
    SegnalazioneArgs,
    build_tools_for,
)
from src.api.agent import router
from src.auth.acl import visible_to
from src.auth.deps import UserContext, get_current_user
from src.db.models import ComplianceAlert
from src.db.repos import AccountRepository
from src.services.retrieval_service import RetrievalResult
from tests.conftest import (
    CLIENTE_ALTRUI,
    CLIENTE_DI_MARCO,
    CONTO_ALTRUI,
    CONTO_DI_MARCO,
    risposta,
)


def _tool(tools: list[Tool], nome: str) -> Tool:
    return next(t for t in tools if t.name == nome)


# ---------------------------------------------------------------- il muro
async def test_i_conti_di_un_cliente_del_portafoglio(deps_reali: Deps, marco: UserContext) -> None:
    esito = await _tool(build_tools_for(marco, deps_reali), "find_customer_accounts").run(
        ClienteArgs(customer_id=CLIENTE_DI_MARCO)
    )
    assert esito == f"Conti del cliente {CLIENTE_DI_MARCO}:\n- {CONTO_DI_MARCO} (principale)"
    assert "Ferri" not in esito  # al modello solo i campi che servono


async def test_un_cliente_altrui_e_uno_inesistente_rispondono_uguale(
    deps_reali: Deps, marco: UserContext
) -> None:
    trova = _tool(build_tools_for(marco, deps_reali), "find_customer_accounts")
    altrui = await trova.run(ClienteArgs(customer_id=CLIENTE_ALTRUI))
    inesistente = await trova.run(ClienteArgs(customer_id="C-99999"))
    assert altrui == inesistente == NON_DISPONIBILE


async def test_saldo_di_un_conto_del_portafoglio(deps_reali: Deps, marco: UserContext) -> None:
    esito = await _tool(build_tools_for(marco, deps_reali), "get_account_balance").run(
        SaldoArgs(account_id=CONTO_DI_MARCO)
    )
    assert esito == f"Saldo di {CONTO_DI_MARCO}: 48200.00 EUR"


async def test_il_repository_e_interrogato_solo_con_l_identita_di_marco(
    deps_spia: MagicMock, marco: UserContext
) -> None:
    saldo = _tool(build_tools_for(marco, deps_spia), "get_account_balance")
    esito = await saldo.run(SaldoArgs(account_id=CONTO_ALTRUI))
    assert esito == NON_DISPONIBILE
    deps_spia.accounts.of_user.assert_awaited_once_with(marco.username, CONTO_ALTRUI)


async def test_la_riga_altrui_non_esce_dal_database(session: AsyncSession) -> None:
    repo = AccountRepository(session)
    assert await repo.of_user("mbianchi", CONTO_ALTRUI) is None
    assert await repo.of_user("pgalli", CONTO_ALTRUI) is not None
    assert await repo.of_customer("mbianchi", CLIENTE_ALTRUI) == []


async def test_il_tentativo_negato_si_registra(
    deps_spia: MagicMock, marco: UserContext, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        await _tool(build_tools_for(marco, deps_spia), "get_account_balance").run(
            SaldoArgs(account_id=CONTO_ALTRUI)
        )
    negato = next(r for r in caplog.records if r.message == "tool_accesso_negato")
    assert negato.__dict__["requested"] == impronta(CONTO_ALTRUI)  # il tentativo, non l'IBAN


def test_stringa_vuota_rifiutata_dalla_validazione() -> None:
    with pytest.raises(ValueError):
        SaldoArgs.model_validate_json('{"account_id": ""}')


# ---------------------------------------------------------------- il tool che scrive
async def test_due_segnalazioni_uguali_fanno_una_riga(
    deps_reali: Deps, session: AsyncSession, marco: UserContext
) -> None:
    segnala = _tool(build_tools_for(marco, deps_reali), "apri_segnalazione_compliance")
    args = SegnalazioneArgs(
        account_id=CONTO_DI_MARCO, motivo="Bonifico verso paese a rischio", importo=Decimal("25000")
    )
    prima = await segnala.run(args)
    seconda = await segnala.run(args)
    righe = await session.scalar(select(func.count()).select_from(ComplianceAlert))
    assert righe == 1
    assert "aperta. Riferisci" in prima and "già aperta" in seconda


async def test_nessuna_segnalazione_su_un_conto_altrui(
    deps_reali: Deps, session: AsyncSession, marco: UserContext
) -> None:
    segnala = _tool(build_tools_for(marco, deps_reali), "apri_segnalazione_compliance")
    esito = await segnala.run(
        SegnalazioneArgs(account_id=CONTO_ALTRUI, motivo="Tentativo su un conto altrui")
    )
    assert esito == NON_DISPONIBILE
    assert await session.scalar(select(func.count()).select_from(ComplianceAlert)) == 0


# ---------------------------------------------------------------- il loop
async def test_due_messaggi_per_giro(deps_reali: Deps, marco: UserContext) -> None:
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(tool="get_account_balance", argomenti=f'{{"account_id": "{CONTO_DI_MARCO}"}}'),
        risposta(testo="Sul conto ci sono 48.200 euro."),
    ]
    run = await run_agent(
        messaggi=[{"role": "user", "content": "saldo di IT60...0123?"}],
        tools=build_tools_for(marco, deps_reali),
        client=client,
        model="gpt-4o-mini",
    )
    inviati = client.chat.completions.create.call_args.kwargs["messages"]
    assert [m["role"] for m in inviati] == ["user", "assistant", "tool"]
    assert inviati[1]["tool_calls"][0]["id"] == inviati[2]["tool_call_id"]
    assert (run.stopped_by, run.steps, run.tool_calls) == ("model", 2, ["get_account_balance"])


async def test_tetto_raggiunto_non_e_una_risposta(deps_reali: Deps, marco: UserContext) -> None:
    client = AsyncMock()
    client.chat.completions.create.return_value = risposta(
        tool="search_documents", argomenti='{"query": "soglie paesi a rischio"}'
    )
    run = await run_agent(
        messaggi=[{"role": "user", "content": "domanda impossibile"}],
        tools=build_tools_for(marco, deps_reali),
        client=client,
        model="gpt-4o-mini",
        max_steps=2,
    )
    assert run.stopped_by == "max_steps" and run.steps == 2
    assert "la risposta non c'è" in run.reply


async def test_budget_superato_ferma_il_run(deps_reali: Deps, marco: UserContext) -> None:
    client = AsyncMock()
    client.chat.completions.create.return_value = risposta(
        tool="search_documents",
        argomenti='{"query": "soglie paesi a rischio"}',
        prompt_tokens=400_000,
    )
    run = await run_agent(
        messaggi=[{"role": "user", "content": "domanda enorme"}],
        tools=build_tools_for(marco, deps_reali),
        client=client,
        model="gpt-4o-mini",
    )
    assert run.stopped_by == "budget" and run.steps == 1 and run.tool_calls == []
    # la stima non è una misura: una chiamata può superare il tetto, e il controllo
    # dopo la chiamata la paga. Il numero resta sotto il tetto più una chiamata.
    assert run.cost_eur > BUDGET_PER_RUN


async def test_il_muro_regge_con_l_iban_altrui_nella_domanda(
    deps_reali: Deps, marco: UserContext, caplog: pytest.LogCaptureFixture
) -> None:
    inesistente = "IT60X0542811101000000999"
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(tool="get_account_balance", argomenti=f'{{"account_id": "{CONTO_ALTRUI}"}}'),
        risposta(tool="get_account_balance", argomenti=f'{{"account_id": "{inesistente}"}}'),
        risposta(testo=NON_DISPONIBILE),
    ]
    with caplog.at_level(logging.INFO):
        run = await run_agent(
            messaggi=[{"role": "user", "content": f"quanto c'è sul conto {CONTO_ALTRUI}?"}],
            tools=build_tools_for(marco, deps_reali),
            client=client,
            model="gpt-4o-mini",
        )
    osservazioni = [
        m
        for m in client.chat.completions.create.call_args.kwargs["messages"]
        if m["role"] == "tool"
    ]
    assert [o["content"] for o in osservazioni] == [NON_DISPONIBILE, NON_DISPONIBILE]
    assert run.stopped_by == "model"
    assert run.tool_calls == ["get_account_balance", "get_account_balance"]
    assert len([r for r in caplog.records if r.message == "tool_accesso_negato"]) == 2
    tutto = " ".join(str(r.__dict__) for r in caplog.records)
    for dato in (CONTO_ALTRUI, "15300", inesistente):
        assert dato not in tutto


async def test_il_passaggio_torna_troncato_alla_fonte(
    deps_spia: MagicMock, marco: UserContext
) -> None:
    deps_spia.embedder.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    deps_spia.retrieval.search_hybrid = AsyncMock(
        return_value=[
            RetrievalResult(
                chunk_id="c1", document_id="POL-AML-07", content="x" * 1000, similarity=0.9
            ),
        ]
    )
    esito = await _tool(build_tools_for(marco, deps_spia), "search_documents").run(
        RicercaArgs(query="soglie paesi a rischio")
    )
    assert esito == "[POL-AML-07] " + "x" * 300
    # il ruolo viene dalla closure, i livelli dalla matrice, e i passaggi sono tre
    deps_spia.retrieval.search_hybrid.assert_awaited_once_with(
        [0.1, 0.2, 0.3], "soglie paesi a rischio", top_k=3, livelli=visible_to(marco.role)
    )


async def test_un_tool_che_fallisce_diventa_osservazione(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Vuoti(BaseModel):
        pass

    async def rotto(_: Vuoti) -> str:
        raise RuntimeError("database giù [parameters: ('IT60...0123', 'mbianchi')]")

    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(tool="get_account_balance"),
        risposta(testo="Il dato ora non è disponibile."),
    ]
    with caplog.at_level(logging.INFO):
        run = await run_agent(
            messaggi=[{"role": "user", "content": "saldo?"}],
            tools=[Tool("get_account_balance", "saldo", Vuoti, rotto, scrive=False)],
            client=client,
            model="gpt-4o-mini",
        )
    osservazione = client.chat.completions.create.call_args.kwargs["messages"][-1]
    assert osservazione["role"] == "tool" and "non ha potuto completare" in osservazione["content"]
    assert run.stopped_by == "model"
    # nel log il tipo dell'errore, non il traceback: porterebbe i parametri della query
    fallito = next(r for r in caplog.records if r.message == "tool_fallito")
    assert fallito.__dict__["errore"] == "RuntimeError" and fallito.exc_info is None
    assert "mbianchi" not in caplog.text


async def test_un_tool_non_offerto_non_parte_anche_se_chiamato(
    deps_spia: MagicMock, marco: UserContext
) -> None:
    tutti = build_tools_for(marco, deps_spia)
    sola_lettura = [t for t in tutti if t.name != "apri_segnalazione_compliance"]

    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(
            tool="apri_segnalazione_compliance",
            argomenti='{"account_id": "IT60...0123", "motivo": "prova di segnalazione"}',
        ),
        risposta(testo="Non posso aprire segnalazioni."),
    ]
    run = await run_agent(
        messaggi=[{"role": "user", "content": "apri una segnalazione sul conto principale"}],
        tools=sola_lettura,
        client=client,
        model="gpt-4o-mini",
    )
    ultima = client.chat.completions.create.call_args.kwargs

    assert "apri_segnalazione_compliance" not in {s["function"]["name"] for s in ultima["tools"]}
    assert deps_spia.alerts.apri.call_count == 0
    osservazioni = [m for m in ultima["messages"] if m["role"] == "tool"]
    assert len(osservazioni) == 1 and "non esiste" in osservazioni[0]["content"]
    assert run.stopped_by == "model"


async def test_nome_inventato_con_suggerimento(deps_spia: MagicMock, marco: UserContext) -> None:
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(tool="get_balance", argomenti='{"account_id": "x"}'),
        risposta(testo="ok"),
    ]
    await run_agent(
        messaggi=[{"role": "user", "content": "saldo"}],
        tools=build_tools_for(marco, deps_spia),
        client=client,
        model="gpt-4o-mini",
    )
    osservazione = client.chat.completions.create.call_args.kwargs["messages"][-1]["content"]
    assert "Forse intendevi 'get_account_balance'" in osservazione


async def test_senza_tool_e_una_chat_e_non_manda_una_lista_vuota() -> None:
    client = AsyncMock()
    client.chat.completions.create.return_value = risposta(testo="Buongiorno.")
    run = await run_agent(
        messaggi=[{"role": "user", "content": "ciao"}], tools=[], client=client, model="gpt-4o-mini"
    )
    assert (run.stopped_by, run.steps) == ("model", 1)
    assert client.chat.completions.create.call_args.kwargs["tools"] is omit


async def test_modello_senza_prezzo_si_ferma_prima_di_spendere(marco: UserContext) -> None:
    client = AsyncMock()
    with pytest.raises(ValueError):
        await run_agent(messaggi=[], tools=[], client=client, model="modello-sconosciuto")
    client.chat.completions.create.assert_not_called()


# ---------------------------------------------------------------- la traccia
async def test_la_traccia_ricostruisce_il_run_e_la_pratica(
    deps_reali: Deps,
    session: AsyncSession,
    marco: UserContext,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(deps_reali.embedder, "embed_query", AsyncMock(return_value=[0.1, 0.2, 0.3]))
    monkeypatch.setattr(
        deps_reali.retrieval,
        "search_hybrid",
        AsyncMock(
            return_value=[
                RetrievalResult(
                    chunk_id="c1",
                    document_id="POL-AML-07",
                    content="Oltre 15.000 EUR verso paesi a rischio serve una segnalazione.",
                    similarity=0.9,
                )
            ]
        ),
    )
    saldo = f'{{"account_id": "{CONTO_DI_MARCO}"}}'
    movimenti = f'{{"account_id": "{CONTO_DI_MARCO}", "n": 5}}'
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(
            tool="find_customer_accounts",
            argomenti=f'{{"customer_id": "{CLIENTE_DI_MARCO}"}}',
        ),
        risposta(tool="get_account_balance", argomenti=saldo),
        risposta(tool="search_documents", argomenti='{"query": "soglie paesi a rischio"}'),
        risposta(tool="list_recent_movements", argomenti=movimenti),
        risposta(tool="get_account_balance", argomenti=saldo),
        risposta(
            tool="apri_segnalazione_compliance",
            argomenti=f'{{"account_id": "{CONTO_DI_MARCO}", '
            '"motivo": "Bonifico di 25.000 EUR verso paese a rischio", '
            '"importo": "25000"}',
        ),
        risposta(testo="Ho aperto la segnalazione: il numero è nella ricevuta."),
    ]
    with caplog.at_level(logging.INFO):
        run = await run_agent(
            messaggi=[
                {"role": "user", "content": "il cliente C-10234 ha un bonifico dal Venezuela"}
            ],
            tools=build_tools_for(marco, deps_reali),
            client=client,
            model="gpt-4o-mini",
        )

    passi = [r.__dict__ for r in caplog.records if r.message == "agent_step"]
    assert [p["tool"] for p in passi] == [
        "find_customer_accounts",
        "get_account_balance",
        "search_documents",
        "list_recent_movements",
        "get_account_balance",
        "apri_segnalazione_compliance",
    ]
    assert [p["result_kind"] for p in passi] == ["ok"] * 6
    # la stessa domanda ripetuta si riconosce dall'impronta, senza il valore
    assert passi[1]["tool_args"] == passi[4]["tool_args"]
    assert passi[-1]["tool_args"] == "<omessi>"

    ricevuta = passi[-1]["receipt"]
    assert ricevuta.startswith("Segnalazione ")
    alert = await session.scalar(select(ComplianceAlert))
    assert alert is not None
    assert alert.id in ricevuta
    assert (alert.account_id, alert.opened_by) == (CONTO_DI_MARCO, marco.username)

    # sei chiamate di tool più la risposta finale: con il tetto a sei la pratica
    # resterebbe nel database senza che il numero arrivi a Marco
    assert (run.stopped_by, run.steps, len(run.tool_calls)) == ("model", 7, 6)
    assert [p["step"] for p in passi] == [1, 2, 3, 4, 5, 6]

    esecuzione = next(r for r in caplog.records if r.message == "agent_run")
    assert esecuzione.__dict__["run_id"] == run.run_id == passi[0]["run_id"]
    assert esecuzione.__dict__["stopped_by"] == "model"
    assert esecuzione.__dict__["steps"] == 7
    assert Decimal(esecuzione.__dict__["cost_eur"]) > 0

    tutto = " ".join(str(r.__dict__) for r in caplog.records)
    for dato in (CONTO_DI_MARCO, CLIENTE_DI_MARCO, "48200", "25000", "Venezuela"):
        assert dato not in tutto


# ---------------------------------------------------------------- l'endpoint
async def test_endpoint(deps_reali: Deps, marco: UserContext) -> None:
    from fastapi import FastAPI

    modello = cast(AsyncMock, deps_reali.openai)  # nel test è il finto di conftest
    modello.chat.completions.create.side_effect = [
        risposta(
            tool="find_customer_accounts", argomenti=f'{{"customer_id": "{CLIENTE_DI_MARCO}"}}'
        ),
        risposta(tool="get_account_balance", argomenti=f'{{"account_id": "{CONTO_DI_MARCO}"}}'),
        risposta(testo="Sul conto principale del cliente ci sono 48.200 euro."),
    ]
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: marco
    app.dependency_overrides[get_deps] = lambda: deps_reali
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/api/ai/agent",
            json={"message": f"quanto c'è sul conto principale del cliente {CLIENTE_DI_MARCO}?"},
        )
    corpo = r.json()
    assert r.status_code == 200
    assert corpo["stopped_by"] == "model" and corpo["steps"] == 3
    assert corpo["tool_calls"] == ["find_customer_accounts", "get_account_balance"]
    assert corpo["cost_eur"] > 0


async def test_gli_argomenti_di_un_tool_che_scrive_non_vanno_nel_log(
    deps_reali: Deps, marco: UserContext, caplog: pytest.LogCaptureFixture
) -> None:
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(
            tool="apri_segnalazione_compliance",
            argomenti=f'{{"account_id": "{CONTO_DI_MARCO}", '
            '"motivo": "Cliente Paolo Ferri, bonifici ripetuti verso Panama", '
            '"importo": "1200"}',
        ),
        risposta(testo="Segnalazione aperta."),
    ]
    with caplog.at_level(logging.INFO):
        await run_agent(
            messaggi=[{"role": "user", "content": "segnala"}],
            tools=build_tools_for(marco, deps_reali),
            client=client,
            model="gpt-4o-mini",
        )
    passo = next(r for r in caplog.records if r.message == "agent_step")
    assert passo.__dict__["tool_args"] == "<omessi>"  # i campi di `extra` finiscono nel record
    assert passo.__dict__["receipt"].startswith("Segnalazione ")  # la pratica, per l'audit
    assert "Ferri" not in str(passo.__dict__)


async def test_un_errore_di_un_tool_che_scrive_non_lascia_ricevuta(
    deps_reali: Deps, marco: UserContext, caplog: pytest.LogCaptureFixture
) -> None:
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(
            tool="apri_segnalazione_compliance",
            argomenti=f'{{"account_id": "{CONTO_DI_MARCO}", "motivo": "Ferri"}}',
        ),
        risposta(testo="Non riuscito."),
    ]
    with caplog.at_level(logging.INFO):
        await run_agent(
            messaggi=[{"role": "user", "content": "segnala"}],
            tools=build_tools_for(marco, deps_reali),
            client=client,
            model="gpt-4o-mini",
        )
    passo = next(r for r in caplog.records if r.message == "agent_step")
    # il motivo è troppo corto: l'errore di validazione lo riporta, e nel log non deve finire
    assert passo.__dict__["result_kind"] == "errore" and passo.__dict__["receipt"] is None
    assert "Ferri" not in " ".join(str(r.__dict__) for r in caplog.records)


async def test_nel_log_il_tipo_dell_esito_e_non_il_dato(
    deps_reali: Deps, marco: UserContext, caplog: pytest.LogCaptureFixture
) -> None:
    saldo_di = '{{"account_id": "{}"}}'.format
    client = AsyncMock()
    client.chat.completions.create.side_effect = [
        risposta(tool="get_account_balance", argomenti=saldo_di(CONTO_DI_MARCO)),
        risposta(tool="get_account_balance", argomenti=saldo_di(CONTO_ALTRUI)),
        risposta(tool="get_account_balance", argomenti=saldo_di(CONTO_DI_MARCO)),
        risposta(tool="get_balance", argomenti=saldo_di(CONTO_DI_MARCO)),
        risposta(testo="Fatto."),
    ]
    with caplog.at_level(logging.INFO):
        await run_agent(
            messaggi=[{"role": "user", "content": "saldi"}],
            tools=build_tools_for(marco, deps_reali),
            client=client,
            model="gpt-4o-mini",
        )
    passi = [r.__dict__ for r in caplog.records if r.message == "agent_step"]
    assert [p["result_kind"] for p in passi] == ["ok", "vuoto", "ok", "errore"]
    # la stessa domanda ripetuta si riconosce dall'impronta, senza che l'IBAN sia nel log
    assert passi[0]["tool_args"] == passi[2]["tool_args"] != passi[1]["tool_args"]
    tutto = " ".join(str(r.__dict__) for r in caplog.records)
    for dato in ("48200", "15300", CONTO_DI_MARCO, CONTO_ALTRUI):
        assert dato not in tutto
