# scripts/misura_tetti.py - baseline p95/costo/ok su dataset advice (best effort)
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
OUT = ROOT / "docs" / "tetti_partenza.json"


def _carica(n: int) -> list[dict[str, object]]:
    casi: list[dict[str, object]] = []
    for line in DATASET.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        casi.append(json.loads(line))
        if len(casi) >= n:
            break
    return casi


async def _login(client: httpx.AsyncClient, base: str) -> str:
    r = await client.post(
        f"{base}/api/auth/login",
        data={"username": "mbianchi", "password": "bootcamp"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--salva", action="store_true")
    args = ap.parse_args()

    casi = _carica(args.n)
    tempi: list[float] = []
    costi: list[float] = []
    ok = 0
    async with httpx.AsyncClient() as client:
        token = await _login(client, args.base_url)
        for caso in casi:
            q = str(caso.get("question", ""))
            t0 = time.perf_counter()
            try:
                r = await client.post(
                    f"{args.base_url}/api/ai/advice",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={"question": q},
                    timeout=60.0,
                )
                dt = (time.perf_counter() - t0) * 1000
                tempi.append(dt)
                if r.status_code == 200:
                    data = r.json()
                    costi.append(float(data.get("cost_eur", 0.0) or 0.0))
                    ans = str(data.get("answer", "")).strip()
                    if ans:
                        ok += 1
                else:
                    costi.append(0.0)
            except Exception:
                dt = (time.perf_counter() - t0) * 1000
                tempi.append(dt)
                costi.append(0.0)

    def p95(vals: list[float]) -> float:
        if not vals:
            return 0.0
        if len(vals) < 2:
            return vals[0]
        return float(statistics.quantiles(vals, n=20)[-1])

    payload = {
        "n": len(casi),
        "p95_ms": p95(tempi),
        "avg_cost_eur": statistics.mean(costi) if costi else 0.0,
        "ok_rate": ok / len(casi) if casi else 0.0,
    }
    print(json.dumps(payload, indent=2))
    if args.salva:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"salvato {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
