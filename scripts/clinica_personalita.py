# scripts/clinica_personalita.py — la stessa domanda, tre prompt: agente unico e i due specialisti
import asyncio
import sys

from src.agents.deps import crea_deps
from src.agents.loop import run_agent
from src.agents.prompts import AGENT_SYSTEM
from src.agents.registry import Tool
from src.agents.supervisor import SPECIALISTI
from src.agents.tools import build_tools_for
from src.auth.deps import UserContext
from src.db.session import AsyncSessionLocal

DOMANDA = "il cliente C-10234 può disporre 25.000 verso il Venezuela dal conto principale?"


async def main(domanda: str) -> None:
    user = UserContext(username="mbianchi", role="operator")
    async with AsyncSessionLocal() as db:
        deps = crea_deps(db)
        tutti = build_tools_for(user, deps)
        casi: list[tuple[str, str, list[Tool]]] = [("agente unico", AGENT_SYSTEM, tutti)]
        for s in SPECIALISTI.values():
            casi.append((f"specialista {s.nome}", s.system_prompt, [t for t in tutti if t.name in s.tool_names]))
        for nome, prompt, tools in casi:
            run = await run_agent(
                messaggi=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": domanda},
                ],
                tools=tools,
                client=deps.openai,
                model=deps.model,
                runs=deps.runs,
                user=user,
            )
            print(f"=== {nome} ===")
            print(f"{run.stopped_by} · passi {run.steps} · tool {run.tool_calls}")
            print(run.reply, "\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else DOMANDA))