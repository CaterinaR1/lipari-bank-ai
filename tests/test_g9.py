# tests/test_g9.py — eval pipeline, ledger, admin, logging, estensione
from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from src.auth.deps import UserContext
from src.db.models import LlmCall
from src.observability.json_log import JsonFormatter, request_id
from src.observability.ledger import CostLedger

ROOT = Path(__file__).resolve().parents[1]


def test_datasets_hanno_dimensione_e_schema_minimo() -> None:
    def righe(nome: str) -> list[dict[str, Any]]:
        p = ROOT / "evals" / "datasets" / nome
        return [
            json.loads(r)
            for r in p.read_text(encoding="utf-8-sig").splitlines()
            if r.strip()
        ]

    cat = righe("categorize.jsonl")
    adv = righe("advice.jsonl")
    traj = righe("agent_traiettorie.jsonl")
    assert len(cat) == 40
    assert len(adv) == 30
    assert len(traj) == 15
    assert all({"id", "description", "expected_category"} <= c.keys() for c in cat)
    assert all({"id", "question", "expected_answer"} <= c.keys() for c in adv)
    assert all({"id", "question", "expected_tools"} <= c.keys() for c in traj)


async def test_cost_ledger_scrive_llm_call(session) -> None:
    ledger = CostLedger(session)
    ledger.aggiungi(
        endpoint="chat",
        username="mbianchi",
        model="gpt-4o-mini",
        tokens=123,
        cost_eur=Decimal("0.001234"),
        run_id="run-1",
    )
    await session.commit()
    row = (await session.execute(select(LlmCall))).scalar_one()
    assert row.endpoint == "chat"
    assert row.username == "mbianchi"
    assert row.tokens == 123
    assert row.cost_eur == Decimal("0.001234")
    assert row.run_id == "run-1"


async def test_cost_ledger_ignora_costo_zero(session) -> None:
    ledger = CostLedger(session)
    ledger.aggiungi(endpoint="chat", username="u", model="m", tokens=0, cost_eur=Decimal("0"))
    await session.commit()
    assert (await session.execute(select(LlmCall))).scalars().all() == []


def test_json_log_include_request_id_e_extra() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "ciao", (), None)
    record.tool = "search_documents"
    token = request_id.set("req-123")
    try:
        line = JsonFormatter().format(record)
    finally:
        request_id.reset(token)
    data = json.loads(line)
    assert data["msg"] == "ciao"
    assert data["request_id"] == "req-123"
    assert data["tool"] == "search_documents"


async def test_admin_cost_report_richiede_ruolo() -> None:
    # dipendenza require_role controllata a livello unitario: ruolo non ammesso -> 403
    from fastapi import HTTPException

    from src.auth.deps import require_role

    dep = require_role("risk_lead", "admin")
    with pytest.raises(HTTPException) as exc:
        await dep(UserContext(username="op", role="operator"))
    assert exc.value.status_code == 403


async def test_admin_cost_report_aggregato(session) -> None:
    session.add_all(
        [
            LlmCall(
                endpoint="chat",
                username="a",
                model="gpt-4o-mini",
                tokens=10,
                cost_eur=Decimal("0.010"),
            ),
            LlmCall(
                endpoint="advice",
                username="b",
                model="gpt-4o",
                tokens=20,
                cost_eur=Decimal("0.020"),
            ),
            LlmCall(
                endpoint="agent",
                username="a",
                model="gpt-4o",
                tokens=30,
                cost_eur=Decimal("0.030"),
                run_id="r1",
            ),
        ]
    )
    await session.commit()
    from datetime import date

    from src.api.admin import cost_report

    rep = await cost_report(date.today(), UserContext(username="admin", role="admin"), session)
    assert rep.totale_eur == Decimal("0.060")
    assert sum(v.chiamate for v in rep.per_endpoint) == 3
    assert {v.chiave for v in rep.per_modello} == {"gpt-4o-mini", "gpt-4o"}


def test_runner_salva_risultato_e_delta(tmp_path, monkeypatch) -> None:
    import evals.runner as runner

    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    first = {"scores": {"categorize": 0.8, "advice": 0.7, "traiettorie": 0.8}}
    p1 = runner.salva_risultato(first)
    assert p1.exists()
    prev = runner.carica_precedente()
    assert prev is not None
    assert prev["scores"]["categorize"] == 0.8
    # delta calcolabile rispetto al precedente


def test_runner_tool_chiamati_da_messaggi() -> None:
    import evals.runner as runner

    msgs = [
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "a"}}, {"function": {"name": "b"}}],
        },
        {"role": "assistant", "tool_calls": [{"function": {"name": "a"}}]},
    ]
    assert runner._tool_chiamati(msgs) == ["a", "b", "a"]


def test_soglie_runner_definite() -> None:
    import evals.runner as runner

    assert runner.SOGLIE == {"categorize": 0.80, "advice": 0.70, "traiettorie": 0.80}
    assert all(0 < v < 1 for v in runner.SOGLIE.values())


def test_workflow_eval_presente_e_configurato() -> None:
    text = (ROOT / ".github" / "workflows" / "eval.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert 'cron: "0 6 * * 1"' in text
    assert "pgvector/pgvector:pg16" in text
    assert "OPENAI_API_KEY" in text
    assert "alembic upgrade head" in text
    assert "scripts.seed_accounts" in text
    assert "evals.ingest_fixtures" in text
    assert "evals.runner" in text


def test_ai_review_g9_presente() -> None:
    p = ROOT / "docs" / "ai-review" / "G9.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "intenzionalmente non corretto" in text.lower() or "non corretto" in text.lower()
    righe = [
        line
        for line in text.splitlines()
        if line.strip().startswith("|") or line.strip().startswith("-")
    ]
    assert len(righe) >= 3
