# tests/unit/test_g7_estensione.py — il tetto si controlla prima di pagare la chiamata
from decimal import Decimal
from unittest.mock import AsyncMock

from src.agents.loop import run_agent


async def test_il_budget_si_ferma_prima_della_chiamata() -> None:
    """Una conversazione già oltre il tetto non fa partire nessuna chiamata."""
    messaggio = "domanda lunga " * 10_000
    for soglia in (Decimal("0.001"), Decimal("0.01"), Decimal("0.05")):
        client = AsyncMock()
        run = await run_agent(
            messaggi=[{"role": "user", "content": messaggio}],
            tools=[],
            client=client,
            model="gpt-4o",
            budget_eur=soglia,
        )
        assert (run.stopped_by, run.steps, run.cost_eur) == ("budget", 0, Decimal("0"))
        assert "budget" in run.reply
        client.chat.completions.create.assert_not_called()
