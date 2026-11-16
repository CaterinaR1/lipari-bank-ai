# evals/runner.py — esegue i tre golden dataset e misura la qualità del sistema
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.agents.deps import Deps
from src.agents.loop import run_agent
from src.agents.prompts import AGENT_SYSTEM
from src.agents.tools import build_tools_for
from src.auth.deps import UserContext
from src.config import settings
from src.db.repos import AccountRepository, MovementRepository
from src.db.runs import RunRepository
from src.llm.embedding_client import EmbeddingClient
from src.llm.factory import get_llm_provider
from src.llm.prompt import load_prompt
from src.llm.rewriter import QueryRewriter
from src.observability.json_log import configura_log
from src.services.alerts import AlertService
from src.services.categorize_service import CategorizeService
from src.services.rag_service import RAGService
from src.services.retrieval_service import RetrievalService
from src.types.categorize import CategorizeRequest

log = logging.getLogger("evals.runner")
ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "evals" / "datasets"
RESULTS = ROOT / "evals" / "results"
RUBRICA = ROOT / "evals" / "judge" / "rubrica_advice.md"

SOGLIE = {"categorize": 0.80, "advice": 0.70, "traiettorie": 0.80}


@dataclass
class Caso:
    dati: dict[str, Any]


def carica(nome: str) -> list[Caso]:
    path = DATASETS / nome
    righe = [r for r in path.read_text(encoding="utf-8-sig").splitlines() if r.strip()]
    return [Caso(json.loads(r)) for r in righe]


def salva_risultato(payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS / f"run-{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = RESULTS / "latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def carica_precedente() -> dict[str, Any] | None:
    path = RESULTS / "latest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


async def valuta_categorize(session: AsyncSession) -> dict[str, Any]:
    from src.llm.factory import get_instructor

    casi = carica("categorize.jsonl")
    servizio = CategorizeService(
        get_instructor(), settings.default_model, load_prompt("categorize_system_v1")
    )
    ok = 0
    dettagli = []
    for caso in casi:
        d = caso.dati
        req = CategorizeRequest(description=d["description"], amount=Decimal(str(d["amount"])))
        try:
            esito = await servizio.categorize(req)
            passato = esito.category == d["expected_category"]
        except Exception as e:
            passato = False
            esito = None
            log.exception("categorize_case_failed", extra={"id": d.get("id"), "err": str(e)})
        if passato:
            ok += 1
        dettagli.append(
            {
                "id": d.get("id"),
                "pass": passato,
                "expected": d["expected_category"],
                "got": getattr(esito, "category", None),
            }
        )
    punteggio = ok / len(casi) if casi else 0.0
    return {"score": punteggio, "passed": ok, "total": len(casi), "cases": dettagli}


async def _giudice(client: AsyncOpenAI, domanda: str, risposta: str, gold: str) -> bool:
    rubrica = RUBRICA.read_text(encoding="utf-8")
    prompt = f"DOMANDA\n{domanda}\n\nRISPOSTA ATTESA\n{gold}\n\nRISPOSTA DEL SISTEMA\n{risposta}\n"
    r = await client.chat.completions.create(
        model=settings.default_model,
        temperature=0,
        messages=[
            {"role": "system", "content": rubrica},
            {"role": "user", "content": prompt},
        ],
        max_tokens=10,
    )
    testo = (r.choices[0].message.content or "").strip().upper()
    return testo.startswith("SI") or testo == "SÌ"


async def valuta_advice(factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    casi = carica("advice.jsonl")
    giudice = AsyncOpenAI(
        api_key=settings.openai_api_key, base_url=settings.openai_base_url or None
    )
    ok = 0
    dettagli = []
    for caso in casi:
        d = caso.dati
        async with factory() as session:
            embedder = EmbeddingClient(
                AsyncOpenAI(api_key=settings.openai_api_key),
                settings.embedding_model,
            )
            rag = RAGService(
                RetrievalService(session),
                embedder,
                get_llm_provider(),
                QueryRewriter(get_llm_provider(), load_prompt("rewrite_system_v1")),
                load_prompt("advice_system_v1"),
                mode=settings.retrieval_mode,
            )
            user = UserContext(username="eval_operator", role=d.get("role", "operator"))
            esito = await rag.advise(d["question"], user, d.get("history"))
            passato = await _giudice(giudice, d["question"], esito.answer, d["expected_answer"])
        if passato:
            ok += 1
        dettagli.append({"id": d.get("id"), "pass": passato, "question": d["question"]})
    punteggio = ok / len(casi) if casi else 0.0
    return {"score": punteggio, "passed": ok, "total": len(casi), "cases": dettagli}


def _tool_chiamati(messages: list[dict[str, Any]]) -> list[str]:
    nomi: list[str] = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {}).get("name")
            if fn:
                nomi.append(fn)
    return nomi


async def valuta_traiettorie(factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    casi = carica("agent_traiettorie.jsonl")
    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
    ok = 0
    dettagli = []
    for caso in casi:
        d = caso.dati
        async with factory() as session:
            deps = Deps(
                accounts=AccountRepository(session),
                movements=MovementRepository(session),
                alerts=AlertService(session),
                runs=RunRepository(session),
                retrieval=RetrievalService(session),
                embedder=EmbeddingClient(
                    AsyncOpenAI(api_key=settings.openai_api_key),
                    settings.embedding_model,
                ),
                openai=client,
                model=settings.default_model,
            )
            user = UserContext(
                username=d.get("username", "mbianchi"),
                role=d.get("role", "operator"),
            )
            run = await run_agent(
                messaggi=[
                    {"role": "system", "content": AGENT_SYSTEM},
                    {"role": "user", "content": d["question"]},
                ],
                tools=build_tools_for(user, deps),
                client=client,
                model=settings.default_model,
                runs=deps.runs,
                user=user,
            )
            stato = await deps.runs.get(run.run_id)
            chiamati = list(run.tool_calls)
            if stato and stato.status == "awaiting_approval":
                pending = [
                    c.get("function", {}).get("name", "") for c in (stato.pending_calls or [])
                ]
                chiamati.extend(pending)
                await deps.runs.chiudi(run.run_id, "closed_by_eval")
            attesi = set(d.get("expected_tools", []))
            pass_tools = attesi.issubset(set(chiamati))
            if d.get("must_not_include_tool"):
                pass_tools = pass_tools and d["must_not_include_tool"] not in chiamati
            if d.get("must_include_tool"):
                pass_tools = pass_tools and d["must_include_tool"] in chiamati
            atteso_stop = d.get("expected_stopped_by")
            pass_stop = True if atteso_stop is None else run.stopped_by == atteso_stop
            passato = pass_tools and pass_stop
        if passato:
            ok += 1
        dettagli.append(
            {
                "id": d.get("id"),
                "pass": passato,
                "tools": chiamati,
                "stopped_by": run.stopped_by,
            }
        )
    punteggio = ok / len(casi) if casi else 0.0
    return {"score": punteggio, "passed": ok, "total": len(casi), "cases": dettagli}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-advice", action="store_true")
    parser.add_argument("--no-agent", action="store_true")
    args = parser.parse_args()
    configura_log(logging.INFO)

    if not settings.openai_api_key:
        print("OPENAI_API_KEY mancante: impossibile eseguire la valutazione live.", file=sys.stderr)
        return 2

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    precedente = carica_precedente()

    async with factory() as session:
        cat = await valuta_categorize(session)

    adv = {"score": None, "skipped": True}
    if not args.no_advice:
        adv = await valuta_advice(factory)
    traj = {"score": None, "skipped": True}
    if not args.no_agent:
        traj = await valuta_traiettorie(factory)

    scores = {
        "categorize": cat["score"],
        "advice": adv.get("score"),
        "traiettorie": traj.get("score"),
    }
    falliti = []
    for nome, soglia in SOGLIE.items():
        s = scores.get(nome)
        if s is not None and s < soglia:
            falliti.append(f"{nome}={s:.2%} < {soglia:.0%}")

    delta = None
    if precedente and precedente.get("scores"):
        prev = precedente["scores"]
        delta = {
            k: (
                None
                if scores.get(k) is None or prev.get(k) is None
                else round(scores[k] - prev[k], 4)
            )
            for k in scores
        }

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "scores": scores,
        "soglie": SOGLIE,
        "delta_vs_previous": delta,
        "details": {"categorize": cat, "advice": adv, "traiettorie": traj},
    }
    path = salva_risultato(payload)
    print(json.dumps({"scores": scores, "delta_vs_previous": delta, "file": str(path)}, indent=2))

    await engine.dispose()
    return 1 if falliti else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
