# src/agents/loop.py
import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import get_close_matches
from typing import cast
from uuid import uuid4

from openai import AsyncOpenAI, omit
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from openai.types.completion_usage import CompletionUsage
from pydantic import ValidationError

from src.agents.registry import Tool, impronta
from src.llm.stima import token_stimati

logger = logging.getLogger(__name__)

MAX_STEPS = 12  # misurato su 10 domande: massimo 10 (Focus con 4 ricerche ripetute), +2 di margine
BUDGET_PER_RUN = Decimal("0.05")  # euro
MAX_TOKEN_USCITA = 500  # il tetto di ogni singola risposta del modello
MARGINE_STIMA_TOKEN = 128  # la stima non è una misura: meglio fermarsi un passo prima
PREZZI_PER_1K = {  # euro per mille token (ingresso, uscita), come nel provider
    "gpt-4o-mini": (Decimal("0.00014"), Decimal("0.00056")),
    "gpt-4o": (Decimal("0.0023"), Decimal("0.0091")),
    # Groq: 0,15/0,60 USD per 1M token. È il DEFAULT_MODEL del .env di sviluppo.
    "openai/gpt-oss-120b": (Decimal("0.00014"), Decimal("0.00056")),
}


@dataclass
class RunResult:
    run_id: str
    reply: str = ""
    steps: int = 0
    tool_calls: list[str] = field(default_factory=list)
    stopped_by: str = ""  # "model" | "max_steps" | "budget"
    cost_eur: Decimal = Decimal("0")


async def run_agent(
    messaggi: list[ChatCompletionMessageParam],
    tools: list[Tool],
    client: AsyncOpenAI,
    model: str,
    max_steps: int = MAX_STEPS,
    budget_eur: Decimal = BUDGET_PER_RUN,
) -> RunResult:
    """Chiama il modello finché chiede tool, poi ritorna la sua risposta.

    Riceve la conversazione e non la domanda: così lo stesso ciclo serve una domanda
    nuova, una conversazione salvata da riprendere e uno specialista con metà dei tool.
    Esce per una delle tre ragioni in `stopped_by`, e chi legge il risultato
    deve poterle distinguere senza guardare il testo della risposta.
    """
    if model not in PREZZI_PER_1K:  # meglio fermarsi qui che scoprirlo dopo aver pagato
        raise ValueError(f"Nessun prezzo per {model}: il budget non sarebbe calcolabile.")
    messaggi = list(messaggi)  # la lista di chi chiama non si tocca
    by_name = {t.name: t for t in tools}  # il dispatch vede SOLO i tool offerti
    schemi = [t.to_openai_schema() for t in tools]
    run = RunResult(run_id=str(uuid4()))  # la chiave di ogni riga di traccia
    risposta_budget = (
        "Ho interrotto l'elaborazione perché la richiesta ha superato il "
        "budget previsto. Prova a formularla in modo più circoscritto."
    )

    try:
        for _ in range(max_steps):  # il tetto è nella struttura
            # la stima viene PRIMA della chiamata: se il prossimo giro sfonda il tetto,
            # non lo pago. Il controllo dopo la chiamata resta per la stima sbagliata.
            previsto = _costo_stimato(messaggi, schemi, model)
            if run.cost_eur + previsto > budget_eur:
                run.stopped_by = "budget"
                run.reply = risposta_budget
                return run

            run.steps += 1
            risposta = await client.chat.completions.create(
                model=model,
                messages=messaggi,
                max_tokens=MAX_TOKEN_USCITA,
                tools=schemi or omit,  # l'API rifiuta una lista vuota
            )
            run.cost_eur += _costo(risposta.usage, model)
            choice = risposta.choices[0].message

            if not choice.tool_calls:  # uscita 1: ha risposto
                run.stopped_by = "model"
                run.reply = choice.content or ""
                return run
            if run.cost_eur > budget_eur:  # uscita 3: il budget, prima di altri tool
                run.stopped_by = "budget"
                run.reply = risposta_budget
                return run

            # PRIMA l'assistant con le chiamate, poi i risultati: altrimenti l'API rifiuta
            assistente = choice.model_dump(exclude_none=True)
            messaggi.append(cast(ChatCompletionAssistantMessageParam, assistente))
            for call in choice.tool_calls:
                if not isinstance(call, ChatCompletionMessageFunctionToolCall):
                    continue  # offriamo solo function tool
                run.tool_calls.append(call.function.name)
                tool = by_name.get(call.function.name)
                inizio = time.perf_counter()
                esito = await _execute(by_name, call)
                tipo = tipo_esito(tool, esito)
                logger.info(
                    "agent_step",
                    extra={
                        "run_id": run.run_id,
                        "step": run.steps,
                        "tool": call.function.name,
                        "tool_args": argomenti_per_il_log(tool, call.function.arguments),
                        "result_kind": tipo,
                        "result_len": len(esito),
                        # di un tool che scrive resta la ricevuta, con il numero di pratica: un
                        # audit risale da lì al run. Solo se è riuscito: un errore riporta gli
                        # argomenti
                        "receipt": esito if tool and tool.scrive and tipo == "ok" else None,
                        "duration_ms": int((time.perf_counter() - inizio) * 1000),
                    },
                )
                messaggi.append({"role": "tool", "tool_call_id": call.id, "content": esito})

        run.stopped_by = "max_steps"  # uscita 2: tetto raggiunto, NON è una risposta
        run.reply = (
            "Non ho completato la richiesta entro i passi previsti: la risposta non c'è. "
            "Riformula la domanda in modo più specifico, o dividila in domande più semplici."
        )
        return run
    finally:
        # una riga per run: il costo e l'uscita, accanto ai singoli passi
        logger.info(
            "agent_run",
            extra={
                "run_id": run.run_id,
                "stopped_by": run.stopped_by,
                "steps": run.steps,
                "tool_calls": run.tool_calls,
                "cost_eur": str(run.cost_eur),
            },
        )


def argomenti_per_il_log(tool: Tool | None, argomenti: str) -> object:
    """Quali campi, quanto lunghi e se si ripetono: non il loro valore."""
    if tool is None or tool.scrive:
        # quelli di un tool che scrive stanno nella sua tabella, con i suoi permessi
        return "<omessi>"
    try:
        valori = json.loads(argomenti)
    except ValueError:
        return "<non leggibili>"
    if not isinstance(valori, dict):
        return "<non leggibili>"
    return {
        campo: v if isinstance(v, int | float) else f"{len(str(v))} car. #{impronta(str(v))}"
        for campo, v in valori.items()
    }


def tipo_esito(tool: Tool | None, esito: str) -> str:
    """Il tipo del risultato al posto del suo testo: basta a separare tool e dato sbagliati."""
    if tool is None or esito.startswith("ERRORE"):
        return "errore"
    return "vuoto" if esito in tool.senza_dati else "ok"


def _token_stimati(
    messaggi: list[ChatCompletionMessageParam], schemi: list[ChatCompletionToolParam]
) -> int:
    """Una stima dichiarata, non una misura: messaggi e schemi, più un margine."""
    testo = json.dumps([messaggi, schemi], ensure_ascii=False, default=str)
    return token_stimati(testo) + MARGINE_STIMA_TOKEN


def _costo_stimato(
    messaggi: list[ChatCompletionMessageParam],
    schemi: list[ChatCompletionToolParam],
    model: str,
) -> Decimal:
    """Il costo peggiore del prossimo giro: input stimato e uscita al tetto."""
    ingresso, uscita = PREZZI_PER_1K[model]
    return (_token_stimati(messaggi, schemi) * ingresso + MAX_TOKEN_USCITA * uscita) / 1000


def _costo(usage: CompletionUsage | None, model: str) -> Decimal:
    if usage is None:
        return Decimal("0")
    ingresso, uscita = PREZZI_PER_1K[model]
    return (usage.prompt_tokens * ingresso + usage.completion_tokens * uscita) / 1000


async def _execute(by_name: dict[str, Tool], call: ChatCompletionMessageFunctionToolCall) -> str:
    tool = by_name.get(call.function.name)
    if tool is None:
        # Il modello ha inventato un nome. Glielo diciamo, non solleviamo — e lo
        # registriamo: un nome inventato con insistenza è un segnale da guardare
        logger.warning("tool_inesistente", extra={"tool": call.function.name[:80]})
        vicini = get_close_matches(call.function.name, list(by_name), n=1)
        suggerimento = f"Forse intendevi '{vicini[0]}'. " if vicini else ""
        elenco = f"Tool disponibili: {', '.join(by_name)}." if len(by_name) <= 10 else ""
        return f"ERRORE: il tool '{call.function.name}' non esiste. {suggerimento}{elenco}".strip()
    try:
        args = tool.args_model.model_validate_json(call.function.arguments)
    except ValidationError as e:
        return f"ERRORE di validazione degli argomenti: {e.errors(include_url=False)}"
    try:
        return await tool.run(args)
    except Exception as e:
        # un tool che fallisce (database lento, vincolo violato) è un'osservazione, non un 500;
        # nel log il tipo dell'errore e non il traceback, che porta con sé l'SQL e i parametri
        logger.error("tool_fallito", extra={"tool": tool.name, "errore": type(e).__name__})
        return (
            f"ERRORE: il tool '{tool.name}' non ha potuto completare l'operazione. "
            "Non riprovare la stessa chiamata: riferisci all'utente che il dato ora non è "
            "disponibile."
        )
