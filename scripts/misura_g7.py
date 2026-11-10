# scripts/misura_g7.py — dieci domande vere all'agente: quanti passi, quali tool, quanto costa
import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FILE = Path("data/eval/domande_g7.jsonl")
BASE_URL = "http://localhost:8000"


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    risposta = await client.post(
        "/api/auth/login", data={"username": username, "password": password}
    )
    risposta.raise_for_status()
    return str(risposta.json()["access_token"])


async def misura(
    base_url: str, limite: int, file: Path, username: str, password: str
) -> int:
    testo = await asyncio.to_thread(file.read_text, encoding="utf-8")
    domande: list[dict[str, Any]] = [
        json.loads(riga) for riga in testo.splitlines() if riga.strip()
    ]
    domande = domande[:limite]
    async with httpx.AsyncClient(base_url=base_url, timeout=300.0) as client:
        token = await login(client, username, password)
        risultati: list[dict[str, Any]] = []
        for domanda in domande:
            risposta = await client.post(
                "/api/ai/agent",
                headers={"Authorization": f"Bearer {token}"},
                json={"message": domanda["domanda"]},
            )
            risposta.raise_for_status()
            corpo: dict[str, Any] = risposta.json()
            risultati.append({**domanda, **corpo})
            tool = ", ".join(corpo["tool_calls"]) or "-"
            print(
                f"{domanda['id']} {domanda['gruppo']:<7} steps={corpo['steps']} "
                f"tool={tool} stop={corpo['stopped_by']} cost={corpo['cost_eur']:.6f}"
            )

    passi = [int(r["steps"]) for r in risultati]
    print()
    print("| id | gruppo | passi | tool | uscita | costo EUR |")
    print("|---|---|---|---|---|---|")
    for r in risultati:
        tool = ", ".join(r["tool_calls"]) or "—"
        print(
            f"| {r['id']} | {r['gruppo']} | {r['steps']} | {tool} | "
            f"{r['stopped_by']} | {r['cost_eur']:.6f} |"
        )
    uscite = sorted({str(r["stopped_by"]) for r in risultati})
    conteggi = ", ".join(
        f"{uscita}: {sum(1 for r in risultati if r['stopped_by'] == uscita)}" for uscita in uscite
    )
    print()
    print(
        f"passi: min={min(passi)} mediana={statistics.median(passi)} max={max(passi)}; "
        f"uscite: {conteggi}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--file", type=Path, default=FILE)
    parser.add_argument("--limite", type=int, default=10)
    parser.add_argument("--username", default="mbianchi")
    parser.add_argument("--password", default="bootcamp")
    args = parser.parse_args()
    return asyncio.run(
        misura(args.base_url, args.limite, args.file, args.username, args.password)
    )


if __name__ == "__main__":
    raise SystemExit(main())
