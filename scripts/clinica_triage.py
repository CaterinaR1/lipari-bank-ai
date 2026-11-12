# scripts/clinica_triage.py — il triage su dieci domande: cosa risponde, e quante finiscono in "entrambi"
import asyncio
import sys
from collections import Counter
from pathlib import Path

from src.agents.supervisor import INSTRADAMENTO, PROMPT_TRIAGE
from src.config import settings
from src.llm.factory import get_openai

# (risposta giusta secondo te, domanda). Per le ambigue scrivi il tuo "giusto" PRIMA di guardare l'uscita
DOMANDE: list[tuple[str, str]] = [
    ("dati_conto", "Quanto c'è sul conto principale del cliente C-10234?"),
    ("dati_conto", "Quali sono gli ultimi cinque movimenti del conto di risparmio di C-10234?"),
    ("dati_conto", "Quali conti ha il cliente C-10234?"),
    ("policy", "Qual è la soglia sopra cui un bonifico verso un paese a rischio non si esegue?"),
    ("policy", "Cosa si dice al cliente quando un'operazione è in verifica?"),
    ("policy", "Chi tiene aggiornato l'elenco dei paesi a rischio elevato?"),
    ("entrambi", "Il cliente C-10234 può disporre 25.000 euro verso il Venezuela dal conto principale?"),
    ("ambigua", "Ha fatto bonifici verso Panama?"),
    ("ambigua", "Posso procedere?"),
    ("ambigua", "Com'è messo il cliente C-10234 sulle soglie?"),
]


async def main(percorso_prompt: str | None) -> None:
    prompt = Path(percorso_prompt).read_text(encoding="utf-8") if percorso_prompt else PROMPT_TRIAGE
    client = get_openai()
    conteggio: Counter[str] = Counter()
    for atteso, domanda in DOMANDE:
        r = await client.chat.completions.create(
            model=settings.triage_model,
            max_tokens=5,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": domanda},
            ],
        )
        grezza = (r.choices[0].message.content or "").strip().lower()
        scelta = grezza if grezza in INSTRADAMENTO else "entrambi"
        nota = "" if grezza in INSTRADAMENTO else f"  <- ripiego, il modello ha scritto {grezza!r}"
        conteggio[scelta] += 1
        print(f"[{atteso:10}] -> {scelta:10} | {domanda}{nota}")
    print("\nTotali:", dict(conteggio))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))