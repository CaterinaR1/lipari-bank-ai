# scripts/bench_cache.py - misura p95/costo con cache calda vs fredda (best effort)
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "datasets" / "advice.jsonl"


def _carica_domande(n: int) -> list[str]:
    domande: list[str] = []
    for line in DATASET.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        q = obj.get("question")
        if isinstance(q, str):
            domande.append(q)
        if len(domande) >= n:
            break
    return domande or ["Quanto costa un bonifico SEPA online?"]


async def _login(client: httpx.AsyncClient, base: str) -> str:
    r = await client.post(
        f"{base}/api/auth/login",
        data={"username": "mbianchi", "password": "bootcamp"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


async def _chiedi(client: httpx.AsyncClient, base: str, token: str, q: str) -> tuple[float, float]:
    t0 = time.perf_counter()
    r = await client.post(
        f"{base}/api/ai/advice",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"question": q},
        timeout=60.0,
    )
    dt = (time.perf_counter() - t0) * 1000
    r.raise_for_status()
    data = r.json()
    cost = float(data.get("cost_eur", 0.0) or 0.0)
    return dt, cost


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()

    domande = _carica_domande(args.n)
    async with httpx.AsyncClient() as client:
        token = await _login(client, args.base_url)

        cold_ms: list[float] = []
        cold_cost: list[float] = []
        for q in domande:
            ms, c = await _chiedi(client, args.base_url, token, q)
            cold_ms.append(ms)
            cold_cost.append(c)

        hot_ms: list[float] = []
        hot_cost: list[float] = []
        for q in domande:
            ms, c = await _chiedi(client, args.base_url, token, q)
            hot_ms.append(ms)
            hot_cost.append(c)

    def p95(vals: list[float]) -> float:
        if len(vals) < 2:
            return vals[0] if vals else 0.0
        return float(statistics.quantiles(vals, n=20)[-1])

    out = {
        "cold": {"p95_ms": p95(cold_ms), "avg_cost_eur": statistics.mean(cold_cost)},
        "hot": {"p95_ms": p95(hot_ms), "avg_cost_eur": statistics.mean(hot_cost)},
        "n": len(domande),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
