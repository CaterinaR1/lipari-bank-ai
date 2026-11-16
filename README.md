Lipari Bank AI

Backend Python per servizi AI, sviluppato con Python 3.12, FastAPI e Pydantic Settings.

Requisiti
Python 3.12
uv
Installazione

Dalla radice del repository:

bash
uv sync --locked
cp .env.example .env


Compila nel file .env i valori obbligatori. Non inserire segreti nel repository.

Per generare un segreto JWT locale:

bash
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"

Avvio

Avvia il server con il comando Uvicorn coerente con il modulo main.py del progetto. Ad esempio, se il modulo Ã¨ src/main.py:

bash
uv run uvicorn main:app --app-dir src --reload


La configurazione viene validata all'avvio. Se manca una variabile obbligatoria, il processo deve fermarsi mostrando un messaggio comprensibile.

Endpoint
GET /health: mostra l'ambiente e lo stato della configurazione delle credenziali, senza rivelarne i valori.
Controlli
bash
uv run ruff check .
uv run mypy src scripts
uv run pytest

Ricostruzione da zero

Eliminare .venv, ricreare l'ambiente seguendo le istruzioni di installazione e avvio di questo README.

Tempo misurato: non misurato in questa sessione (richiede ricostruzione ambiente da zero).
Primo punto di blocco: non registrato in questa sessione.
Scelte delle dipendenze di sviluppo

Ruff, mypy e pytest sono strumenti di sviluppo e sono dichiarati nel gruppo dedicato di pyproject.toml. Sono separati dalle dipendenze runtime per evitare di installare strumenti di verifica nell'ambiente di produzione. La scelta viene verificata con uv sync --locked e con i tre comandi di controllo documentati sopra.

## Giorno 2 â€” come si lancia
uv sync
uv run uvicorn src.main:app --reload        # API su http://localhost:8000, docs su /docs
uv run python -m http.server 5173 --directory client   # pagina di prova, da aprire su localhost:5173
uv run ruff check . && uv run mypy src scripts && uv run pytest

## Il contratto
- POST /api/ai/categorize: classifica un movimento (regola a parole chiave) e dichiara la
  confidenza (0.8 un indizio, 0.5 indizi in conflitto, 0.2 nessun indizio).
- POST /api/ai/movements/import: CSV con intestazione date,description,amount,currency.
  Risponde imported_count e problems (row, reason) per ogni riga rifiutata.
- Ogni errore ha la stessa busta (timestamp, status, error, message, path, details), compresi
  404, 405, 422 e 500. Il 500 non contiene traceback nÃ© percorsi di file.
- X-Request-Id: se il chiamante ne manda uno valido (8-64 caratteri fra lettere, cifre e
  trattini) torna uguale, altrimenti se ne genera uno.

## Importazione: righe buone importate, righe sbagliate spiegate
Ho tenuto la scelta del servizio: le righe valide si importano e ogni riga scartata si dichiara
col suo numero di riga.
Chi usa l'endpoint Ã¨ un ufficio che carica un file al giorno: con 7 righe sbagliate su 200,
rifiutare tutto significherebbe perdere la giornata per un errore di 7 righe, mentre cosÃ¬ sa
quali righe correggere. Ho scartato il rifiuto dell'intero file perchÃ© in quel caso l'ufficio non
saprebbe quali righe sono buone.
Lo so da un test: 16 righe di cui 10 sbagliate in modi diversi, e le righe dopo l'errore non
spariscono dal conto. Il conto torna sempre: righe non vuote = imported_count + len(problems).
Il costo: se l'ufficio carica di nuovo lo stesso file dopo averlo corretto, le righe giÃ 
importate si importano due volte. Oggi non importa, perchÃ© non c'Ã¨ un database; dal Giorno 3 sÃ¬.

## Estensione scelta
- Scelta: confronto automatico con il run precedente (`evals/results/latest.json`) e calcolo `delta_vs_previous` per ogni suite nel runner.
- Perché: rende visibili regressioni/miglioramenti tra esecuzioni senza cambiare il flusso di valutazione live.
- Prova: `tests/test_g9.py::test_runner_salva_risultato_e_delta` verifica persistenza `latest.json` e lettura del run precedente.
## Giorno 3 â€” come si lancia
docker compose up -d
uv run alembic upgrade head
uv run python -m scripts.seed_accounts
uv run uvicorn src.main:app --reload
# test (database lipari_ai_test: docker compose exec postgres createdb -U lipari lipari_ai_test)
uv run ruff check . && uv run mypy src scripts && uv run pytest

## Chi chiude la transazione
Il commit sta nel service, una volta per operazione. Ho scartato il commit in `get_db`, perchÃ©
dopo lo yield gira quando la risposta Ã¨ giÃ  partita: un commit che fallisce lascerebbe al client
un 200 per un dato che non c'Ã¨. Lo so da un test che fa fallire il commit e verifica il 500.

## Estensione: un movimento aggiorna anche il saldo
POST /api/ai/accounts/{id}/movements scrive il movimento e somma l'importo al saldo in una sola
transazione. Ho scartato di leggere il saldo e riscriverlo da Python (due richieste insieme si
sovrascrivono): la somma la fa Postgres con UPDATE ... SET balance = balance + :delta.
Lo so da un test che fa fallire l'aggiornamento del saldo e verifica che il movimento non resti.

## Importi con tre decimali
Si rifiutano con un 422. Ho scartato l'arrotondamento in silenzio di Numeric(12, 2): 12.345
diventerebbe 12.35 senza che nessuno lo sappia.

## Giorno 4 â€” come si lancia
```bash
docker compose up -d
uv run alembic upgrade head
uv run python -m scripts.seed_accounts
uv run uvicorn src.main:app --reload
uv run ruff check . && uv run mypy src scripts && uv run pytest
```
Nel `.env` servono `OPENAI_API_KEY`, `OPENAI_BASE_URL` e `DEFAULT_MODEL`.
- Groq (tier gratuito): `OPENAI_BASE_URL=https://api.groq.com/openai/v1`,
  `DEFAULT_MODEL=openai/gpt-oss-120b`.
- OpenRouter (modello `:free`, nessun acquisto): `OPENAI_BASE_URL=https://openrouter.ai/api/v1`,
  `DEFAULT_MODEL=dots-studio/dots-3-note-preview:free`.
- Anthropic: `ANTHROPIC_API_KEY` e `DEFAULT_MODEL=claude-haiku-4-5-20251001` (richiede una chiave
  a pagamento).

## Il fornitore si cambia da una variabile
`DEFAULT_MODEL` decide il fornitore nella factory (`src/llm/factory.py`): prefisso `claude` â†’
Anthropic, tutto il resto â†’ OpenAI (o un endpoint compatibile indicato da `OPENAI_BASE_URL`).
Service, endpoint e tipi non cambiano.

OpenAI â†” Anthropic: cambia solo `DEFAULT_MODEL`, perchÃ© entrambe le chiavi stanno nel `.env`.
Groq â†” OpenRouter: sono due endpoint dello stesso SDK OpenAI, quindi cambiano `DEFAULT_MODEL`,
`OPENAI_BASE_URL` e `OPENAI_API_KEY`; il codice resta lo stesso. La prova del contratto fra due
implementazioni diverse del `Protocol` Ã¨ nei test; la demo live gratuita usa Groq â†” OpenRouter
perchÃ© Anthropic richiede una chiave a pagamento.

## L'output strutturato resta sull'SDK di OpenAI
La categorizzazione usa `instructor.from_openai(...)` (`src/llm/factory.py`): anche quando la chat
parla con Anthropic, l'output strutturato passa dall'SDK di OpenAI. Non ci sono due strade da
mantenere per lo stesso schema.

## Dove si conta il costo
Lo calcola il provider, che Ã¨ l'unico a vedere i token consumati; il service somma i giri della
tool-call e salva una riga per risposta; il `CostTracker` legge la somma del giorno e la confronta
col tetto. Tengo questa divisione perchÃ© ogni pezzo fa una cosa sola e il tetto non deve fidarsi
del chiamante.

Il prezzo Ã¨ quello di listino, non il tier gratuito: Groq `gpt-oss-120b` costa 0,00014/0,00056 EUR
per 1000 token e OpenRouter `:free` costa 0. CosÃ¬ il tetto conta quello che il fornitore
chiederebbe davvero e la demo mostra due costi diversi; con entrambi a zero il tetto non
scatterebbe mai.

## Estensione scelta: lo streaming sopravvive all'interruzione
Se il client chiude a metÃ , salvo il testo parziale giÃ  inviato e il suo costo stimato (~4
caratteri per token, dichiarato come stima) cosÃ¬ il tetto non si aggira chiudendo la pagina. Ho
scartato di non salvare nulla perchÃ© avrebbe permesso di spendere senza contare. Lo so da un test:
20 interruzioni su 20 lasciano 20 righe assistant con `cost_eur > 0`.
```bash
uv run pytest "tests/test_g4.py::test_stream_interrotto_salva_parziale_e_costo_su_venti_su_venti" -q
```

## Le quattro prove di quello che non deve accadere
```bash
# 1. conto di un altro portafoglio: rifiuta lo strumento, e il log dice strumento_negato
uv run pytest "tests/test_g4.py::test_il_conto_di_un_altro_portafoglio_lo_rifiuta_lo_strumento" -q
# 2. tetto a zero: 429 pulito, il modello non viene chiamato
uv run pytest "tests/test_g4.py::test_il_tetto_a_zero_rifiuta_prima_di_chiamare_il_modello" -q
# 3. output fuori schema: Instructor ritenta e poi 502, niente spazzatura salvata
uv run pytest "tests/test_g4.py::test_instructor_ritenta_e_ogni_tentativo_e_una_chiamata" -q
# 4. streaming interrotto: parziale e costo stimato restano nel database (20/20)
uv run pytest "tests/test_g4.py::test_stream_interrotto_salva_parziale_e_costo_su_venti_su_venti" -q
```

## Demo di due minuti
Avvia i due fornitori sullo stesso database. Il primo legge Groq dal `.env`; il secondo
sovrascrive endpoint, chiave e modello nel proprio terminale (PowerShell):
```powershell
# terminale 1 â€” Groq, costo a listino
$env:DEFAULT_MODEL="openai/gpt-oss-120b"; uv run uvicorn src.main:app --port 8000

# terminale 2 â€” OpenRouter, modello :free (chiave sk-or-v1-...)
$env:OPENAI_BASE_URL="https://openrouter.ai/api/v1"
$env:OPENAI_API_KEY="sk-or-v1-..."
$env:DEFAULT_MODEL="dots-studio/dots-3-note-preview:free"
uv run uvicorn src.main:app --port 8001
```
Poi, a paritÃ  di domanda:
```bash
curl -s -X POST localhost:8000/api/ai/chat -H "Content-Type: application/json" \
  -d '{"session_id":"new","message":"Quanto c e sul conto IT60X0542811101000000123?"}'
curl -s -X POST localhost:8001/api/ai/chat -H "Content-Type: application/json" \
  -d '{"session_id":"new","message":"Quanto c e sul conto IT60X0542811101000000123?"}'
```
I due `cost_eur` sono diversi perchÃ© i listini sono diversi; la forma della risposta e il percorso
sono gli stessi. Poi il tentativo sul conto di Anna Greco (`IT60X0542811101000000789`): risponde
lo strumento con un errore, e nel log compare `strumento_negato`. Per il 429 basta avviare con
`$env:DAILY_BUDGET_EUR="0"` e rifare una domanda.

La prova una-variabile OpenAI â†” Anthropic resta la stessa: nel secondo terminale basta
`$env:DEFAULT_MODEL="claude-haiku-4-5-20251001"` e `ANTHROPIC_API_KEY` nel `.env`. Non l'ho
eseguita live perchÃ© la chiave Anthropic richiede un acquisto; la copre il test con le HTTP finte.

Il tier free di OpenRouter Ã¨ limitato a 20 richieste al minuto e 50 al giorno senza crediti: basta
per questa demo, non per un uso reale. Alcuni modelli `:free` hanno anche un limite upstream: se
rispondono 429, cambia modello (per esempio `dots-studio/dots-3-note-preview:free` oppure
`openrouter/free`). I modelli `:free` possono usare i prompt per il training: usa solo i dati finti
del seed, mai dati reali di clienti.

## Giorno 5 â€” come si lancia
```bash
docker compose up -d                         # Postgres 16 con pgvector
uv run alembic upgrade head                  # chunk a 384 dimensioni, cost_events, GIN
uv run python -m scripts.seed_users          # i tre utenti di sviluppo (password: bootcamp)
uv run uvicorn src.main:app --reload         # secondo terminale: API su http://localhost:8000
uv run python -m scripts.ingest_docs         # terzo terminale: Giulia ingerisce data/docs/*.md
uv run python -m scripts.prove_g5            # le quattro prove live
uv run python -m scripts.valuta_retrieval --mode vector
uv run python -m scripts.valuta_retrieval --mode hybrid
uv run ruff check . && uv run mypy src scripts && uv run pytest
```
`scripts/ingest_docs.py` fa login come `grossi` (compliance_lead) e passa dall'endpoint
`POST /api/ai/documents/ingest`: il server deve essere giÃ  su. Il livello di visibilitÃ  Ã¨ preso
dalla sottocartella (`public`, `internal`, `risk_only`, `compliance_only`). Gli embedding sono
locali (`EMBEDDING_BACKEND=local`, `intfloat/multilingual-e5-small`, 384 dimensioni): al primo uso
fastembed scarica il modello ONNX, poi resta nella cache. Non serve `EMBEDDING_API_KEY`; il
percorso OpenAI resta disponibile con `EMBEDDING_BACKEND=openai` e una chiave vera. Per i test
serve il database di prova:
`docker compose exec postgres createdb -U lipari lipari_ai_test`.

Le domande si fanno cosÃ¬, una volta che il corpus Ã¨ nell'indice e l'utente ha fatto login:
```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -d "username=mbianchi&password=bootcamp" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -s -X POST localhost:8000/api/ai/advice \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Quanto costa il bonifico istantaneo SEPA?"}'
```

## Le scelte del RAG
- **384 dimensioni locali**: `intfloat/multilingual-e5-small`, lo stesso modello per i documenti
  (`passage:`) e per la domanda (`query:`). I prefissi sono la convenzione di E5: senza, i due lati
  non sono addestrati a stare vicini. Ho scelto un modello locale perchÃ© non costa a chiamata,
  lascia i documenti dentro la macchina ed Ã¨ deterministico nei test; pago il download del modello
  ONNX, l'uso di CPU e un tetto di qualitÃ  piÃ¹ basso di un modello API grande.
- **Chunk da 500 caratteri, sovrapposizione 50**: 500 tengono un concetto intero senza portarsi
  dietro mezzo documento; 50 evitano di perdere una frase che cade sul confine. Il taglio cerca
  prima `. `, `? `, `! ` e `\n\n` dopo metÃ  finestra, e solo se non li trova taglia a 500. Prima
  del taglio tolgo i paragrafi identici (una pagina incollata due volte), perchÃ© con l'overlap le
  copie non sarebbero mai chunk uguali. Chunk piÃ¹ piccoli sono piÃ¹ precisi ma perdono contesto e
  fanno piÃ¹ chiamate; chunk piÃ¹ grandi mescolano piÃ¹ argomenti e il top-k porta rumore.
- **HNSW con coseno**: indice `vector_cosine_ops`, top-k 5, soglia di default 0.35 sul vettoriale.
  HNSW guadagna velocitÃ  (non confronta la domanda con tutti i vettori) e paga RAM, spazio, tempo
  di costruzione e insert piÃ¹ lenti. Senza indice la ricerca Ã¨ esatta ma O(n). La variante ibrida
  alza il cancello a 0.85: su questi documenti i positivi in linguaggio naturale stanno da 0.852 in
  su, le negative plausibili fino a 0.851. Su un corpus nuovo va rimisurata; non Ã¨ un numero
  universale.
- **Contesto etichettato**: ogni passaggio arriva al modello come
  `[fonte-N] (documento: ...)`, cosÃ¬ puÃ² citare quello preciso e non un altro.
- **Citazioni**: `citazioni()` legge i `[fonte-N]` presenti nella risposta, accetta anche le
  parentesi larghe `ã€fonte-Nã€‘` che il modello produce a volte, scarta i numeri fuori intervallo e
  deduplica. Il client riceve i chunk davvero citati, non tutto il top-k.
- **Fuori soglia**: nessun passaggio vuol dire rifiuto, senza chiamare il modello; cosÃ¬ non si
  spende per una domanda che i documenti non coprono.
- **Tetto e guasti**: l'advisor controlla lo stesso `CostTracker` della chat prima di spendere
  (429), salva la propria spesa in `cost_events` e un guasto dell'embedder o del modello diventa
  `LLMProviderError` (502), come nella chat.

## Estensione del Giorno 5: ricerca ibrida con cancello di plausibilitÃ 
L'ibrida resta disponibile con `RETRIEVAL_MODE=hybrid`; dal Giorno 6 il default Ã¨ `vector` a 0.35,
perchÃ© la novitÃ  Ã¨ il filtro per ruolo e non voglio sommare due variabili nella stessa misura.
Il vettore da solo trova quasi sempre il documento giusto, ma non sempre il passaggio giusto: su
importi e codici il coseno puÃ² mettere davanti un documento simile e lasciare fuori il chunk che
contiene il dato. Ho aggiunto una gamba lessicale `tsvector('italian')` con indice GIN e fuso i
ranghi con Reciprocal Rank Fusion (`1/(60 + posizione)`), non i punteggi: coseno e `ts_rank` hanno
scale diverse e sommarli farebbe vincere la lista con i numeri piÃ¹ alti per caso.

La ricerca lessicale gira in due versioni: **larga** (termini in OR) per la copertura, **stretta**
(termini in AND) per la precisione su "10.000 EUR" o su un codice composto. Il largo non puÃ² perÃ²
tirare dentro un documento che nÃ© il vettore (sopra 0.85) nÃ© lo stretto hanno trovato: se nessuno
dei due lo vede, la fusione torna vuota e la risposta Ã¨ il rifiuto. Ãˆ il **cancello di
plausibilitÃ **, ed Ã¨ quello che trasforma una domanda fuori corpus in zero passaggi invece di
cinque passaggi agganciati alla parola "conto".

Ho scartato:
- **sommare i punteggi grezzi** (coseno + `ts_rank`): numeri non confrontabili;
- **solo lessico**: trova i codici ma riempie il top-k di passaggi che condividono una parola;
- **alzare solo la soglia**: a 0.852 separerebbe l'ultima negativa, ma Ã¨ a un millesimo dal
  positivo piÃ¹ debole; sarebbe overfitting su 16 domande. La soglia resta 0.85 e l'ultima negativa
  la gestisce il modello con il rifiuto.

La misura, con `k=5`, baseline vettoriale a soglia 0.35 e ibrida a 0.85:

| insieme | sistema | doc@5 | chunk@5 | doc@1 | MRR | negative con passaggi |
|----------|---------|-------|---------|-------|-----|------------------------|
| naturale (11+5) | vettoriale 0.35 | 11/11 | 11/11 | 10/11 | 0.955 | 5/5 |
| naturale (11+5) | vettoriale 0.85 | 11/11 | 10/11 | 10/11 | 0.955 | 1/5 |
| naturale (11+5) | ibrida 0.85 | 11/11 | 11/11 | 10/11 | 0.955 | 1/5 |
| esatte (20) | vettoriale 0.35 | 18/20 | 16/20 | 9/20 | 0.642 | â€” |
| esatte (20) | vettoriale 0.85 | 4/20 | 4/20 | 4/20 | 0.200 | â€” |
| esatte (20) | ibrida 0.85 | 18/20 | 18/20 | 17/20 | 0.875 | â€” |
| totale (31+5) | vettoriale 0.35 | 29/31 | 27/31 | 19/31 | 0.753 | 5/5 |
| totale (31+5) | ibrida 0.85 | 29/31 | 29/31 | 27/31 | 0.903 | 1/5 |

Il doc@5 non si muove fra baseline 0.35 e ibrida 0.85: sull'insieme naturale Ã¨ giÃ  al tetto, e
sulle esatte i due sistemi sbagliano due domande diverse. Ma la tabella mostra perchÃ© servono
entrambe le cose: a 0.85 il vettoriale da solo perde 16 domande esatte su 20, perchÃ© il coseno di
un codice o di un importo spesso sta sotto soglia; a 0.35 le negative entrano tutte. L'ibrida
prende il meglio: il cancello a 0.85 tiene fuori 4 negative su 5, il lessico recupera i codici e
gli importi. Si muovono il passaggio giusto (chunk@5 0.871 â†’ 0.935), il primo documento (doc@1
0.613 â†’ 0.871), l'MRR (0.753 â†’ 0.903) e le negative (5/5 â†’ 1/5). I numeri si rifanno con:
```bash
# insieme naturale
uv run python -m scripts.valuta_retrieval --mode vector --soglia 0.35
uv run python -m scripts.valuta_retrieval --mode vector
uv run python -m scripts.valuta_retrieval --mode hybrid
# insieme esatto
uv run python -m scripts.valuta_retrieval --mode vector --soglia 0.35 --file data/eval/domande_g5_esatte.jsonl
uv run python -m scripts.valuta_retrieval --mode vector --file data/eval/domande_g5_esatte.jsonl
uv run python -m scripts.valuta_retrieval --mode hybrid --file data/eval/domande_g5_esatte.jsonl
```

## Le quattro prove del cancello
`uv run python -m scripts.prove_g5` parla con l'indice vero e con il modello vero (Groq). Stampa
`PASS` per:
1. domanda fuori corpus: rifiuto esatto, nessuna citazione, `tokens_used=0` e costo 0, cioÃ¨ il
   modello non viene chiamato;
2. stesso documento caricato due volte: 2 â†’ 2 passaggi, una citazione, una sola distinta;
3. pagina incollata due volte: 1 â†’ 1 passaggio, una citazione, nessun doppione;
4. domanda vaga ("bonifico estero"): vettoriale e ibrida restituiscono passaggi e la risposta cita
   almeno una fonte; poi stampa i cinque passaggi, cosÃ¬ si vede che cosa ha pescato.

## Su quali domande funziona e su quali no
Funziona sulle domande fattuali coperte da un passaggio dei documenti: "quanto costa il bonifico
istantaneo", "qual Ã¨ il canone della carta oro", "quanto costano i prelievi ATM di altre banche".
Funziona anche sui codici e sugli importi esatti, dove il vettore da solo perde il passaggio:
`15.000 EUR`, `PRCEST07`, `â‚¬1.00`. Non funziona:
- fuori corpus (mutui, investimenti, prodotti che non ho caricato): risponde il rifiuto, che Ã¨ il
  comportamento voluto;
- su due domande esatte con troppe parole ("A cosa serve la MODEST50?", "Dove trovo la Lista
  GRUPPO-A?"): il coseno scende sotto 0.85 e il lessico stretto non trova tutti i termini, quindi
  il cancello le scarta. Il lessico largo le troverebbe, ma Ã¨ proprio quello che il cancello
  blocca per non far entrare le negative;
- su una negativa su cinque (`q16`, "documenti per aprire un conto titoli") il vettore resta a
  0.851 e passa la soglia: i passaggi arrivano, ma il modello risponde con il rifiuto (verificato
  live: 585 token, zero citazioni). Ãˆ il rilievo che non ho corretto: alzare la soglia a 0.852 lo
  eliminerebbe sbilanciando il positivo piÃ¹ debole, e non Ã¨ una scelta robusta su 16 domande;
- sulle domande che vogliono il dato di un cliente (saldo, movimenti): quello Ã¨ il percorso
  chat/tool, non l'advisor, che non legge i conti;
- sulle domande che sommano piÃ¹ documenti senza un passaggio che li copra: il top-k porta i due
  pezzi ma la risposta puÃ² citarne uno solo;
- sui riferimenti impliciti ("e per la oro?"): fino al Giorno 5 il vettore della domanda da sola
  non conteneva il turno precedente. Dal Giorno 6 `AdviceRequest.history` porta gli ultimi turni al
  riscrittore; senza `history` il limite resta.

## Giorno 6 â€” chi sei e cosa puoi vedere
```bash
docker compose up -d
uv run alembic upgrade head                  # app_users e document_chunks.visibility
uv run python -m scripts.seed_users          # mbianchi/operator, grossi/compliance_lead, lverdi/risk_lead
uv run uvicorn src.main:app --reload         # secondo terminale: API su http://localhost:8000
uv run python -m scripts.ingest_docs         # terzo terminale: 13 file, livello dalla sottocartella
uv run python -m scripts.valuta_rewrite      # riscrittore: senza vs con
uv run python -m scripts.valuta_rewrite --storia   # estensione: senza vs con la storia
uv run ruff check . && uv run mypy src scripts && uv run pytest
```
Il login restituisce un JWT di 30 minuti; ogni chiamata all'advisor porta
`Authorization: Bearer <token>`. Le due funzioni seguenti evitano di copiare il token a mano:
```bash
login() { curl -s -X POST localhost:8000/api/auth/login \
  -d "username=$1&password=bootcamp" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])"; }
MARCO=$(login mbianchi)
GIULIA=$(login grossi)
```
La verifica del canarino usa la frase unica del documento riservato ("tre istruttorie su
controparti ricorrenti", `data/docs/compliance_only/aml_controparti_venezuela.md`). La stessa
domanda, due ruoli:
```bash
DOMANDA='{"question":"Quante istruttorie sono in corso sulle controparti venezuelane?"}'
curl -s -X POST localhost:8000/api/ai/advice -H "Authorization: Bearer $MARCO" \
  -H "Content-Type: application/json" -d "$DOMANDA"
curl -s -X POST localhost:8000/api/ai/advice -H "Authorization: Bearer $GIULIA" \
  -H "Content-Type: application/json" -d "$DOMANDA"
```
Marco (`operator`) non riceve la frase nÃ© una citazione `aml_controparti_venezuela`; Giulia
(`compliance_lead`) la riceve e cita il documento. Entrambe le risposte mostrano `rewritten_query`,
cioÃ¨ cosa Ã¨ stato cercato al posto dell'utente.

### Misura della riscrittura
`scripts/valuta_rewrite.py` usa un indice vero e le riscritture registrate nei due dataset, cosÃ¬ il
numero si rifÃ  senza chiave API (`--rigenera` le produce col modello, se serve). Con `k=5` e
soglia 0.35:

| misura | senza | con | delta |
|---|---|---|---|
| 10 domande, riscrittore | doc@1 0.900, MRR 0.950, doc@5 1.000 | doc@1 1.000, MRR 1.000, doc@5 1.000 | doc@1 +0.100, MRR +0.050 |
| 5 follow-up, storia | chunk@5 0.800, doc@1 0.200, MRR 0.500 | chunk@5 1.000, doc@1 0.800, MRR 0.900 | chunk@5 +0.200, doc@1 +0.600, MRR +0.400 |

La riga delle 10 domande Ã¨ la linea di partenza richiesta dalla prima mezz'ora; la riga dei 5
follow-up Ã¨ l'estensione. I follow-up grezzi (senza riscrittura) stanno a doc@5 0.400, quindi la
storia non Ã¨ un dettaglio: senza, la domanda ellittica non contiene il documento giusto.

### Estensione scelta: la storia nel riscrittore
- **Scelto**: `AdviceRequest.history` porta gli ultimi turni; `rewrite_cached` mette nella chiave
  gli ultimi tre, cosÃ¬ la riscrittura di una conversazione non si riusa in un'altra.
- **Scartato**: la cache solo-domanda (restituisce la riscrittura di un'altra conversazione) e la
  riscrittura senza storia (non risolve "e per quello di prima?").
- **Numero**: sui 5 follow-up il MRR passa da 0.500 a 0.900, il chunk@5 da 0.800 a 1.000 e il
  doc@1 da 0.200 a 0.800. Il prezzo Ã¨ che la cache si riusa solo dentro la stessa conversazione.

## Demo di due minuti
1. `docker compose up -d && uv run alembic upgrade head && uv run python -m scripts.seed_users`.
2. `uv run uvicorn src.main:app --reload` in un secondo terminale, poi
   `uv run python -m scripts.ingest_docs`.
3. Login di Marco e Giulia con le due funzioni `login` qui sopra; stessa domanda canarino a
   entrambi: Marco non vede la frase, Giulia sÃ¬, con le due liste di fonti accanto e
   `rewritten_query` visibile in entrambe.
4. Domanda con la storia:
   `-d '{"question":"E per i clienti storici?","history":["Qual Ã¨ il canone annuo della carta oro?"]}'`
   e mostrare `rewritten_query` = "Qual Ã¨ il canone annuo della carta di credito oro per i clienti
   storici?".
5. `uv run python -m scripts.valuta_rewrite && uv run python -m scripts.valuta_rewrite --storia`:
   le due tabelle con i delta.

## Giorno 7 â€” l'agente che usa i tool
```bash
docker compose up -d
uv run alembic upgrade head
uv run python -m scripts.seed_accounts
uv run python -m scripts.seed_users
uv run uvicorn src.main:app --reload        # API su http://localhost:8000
# secondo terminale, a server avviato
uv run python -m scripts.ingest_docs
uv run python -m scripts.misura_g7 --limite 10
uv run ruff check . && uv run mypy src scripts && uv run pytest
```
L'agente ha cinque tool: `find_customer_accounts`, `get_account_balance`,
`list_recent_movements`, `search_documents` e `apri_segnalazione_compliance`. I tool nascono da
`build_tools_for(user, deps)` e l'identitÃ  sta nella closure: il modello non puÃ² passare un altro
utente. Il tool che scrive ricontrolla il portafoglio nel service, e la pratica Ã¨ idempotente per
conto, autore, giorno e importo.

La differenza con una chat Ã¨ strutturale: la chat fa una chiamata; l'agente ripete
modello â†’ tool â†’ modello e termina per `model`, `max_steps` o `budget`. Un tool che solleva
un'eccezione non diventa un 500: `_execute` la trasforma in un'osservazione `ERRORE...`, logga
`tool_fallito` con il tipo e lascia al modello la scelta; un tool che scrive non lascia ricevuta se
gli argomenti non sono validi. Le prove sono `test_un_tool_che_fallisce_diventa_osservazione` e
`test_un_errore_di_un_tool_che_scrive_non_lascia_ricevuta`.

### La misura di `max_steps`
La misura live su 10 domande di `data/eval/domande_g7.jsonl`:

| id | gruppo | passi | tool | uscita | costo EUR |
|---|---|---|---|---|---|
| q01 | uno | 2 | get_account_balance | model | 0.000300 |
| q06 | multi | 10 | find_customer_accounts, get_account_balance Ã—2, list_recent_movements, search_documents Ã—4, apri_segnalazione_compliance | model | 0.003033 |
| q11 | nessuno | 1 | â€” | model | 0.000147 |
| q02 | uno | 2 | list_recent_movements | model | 0.000365 |
| q07 | multi | 4 | find_customer_accounts, get_account_balance, list_recent_movements | model | 0.000831 |
| q12 | nessuno | 1 | â€” | model | 0.000192 |
| q03 | uno | 2 | find_customer_accounts | model | 0.000323 |
| q08 | multi | 4 | list_recent_movements, get_account_balance, search_documents | model | 0.001000 |
| q13 | nessuno | 1 | â€” | model | 0.000138 |
| q04 | uno | 2 | search_documents | model | 0.000512 |

Passi: minimo 1, mediana 2, massimo 10. Uscite: `model` 10/10. Il massimo Ã¨ `q06`, la domanda
multi-tool che ripete `search_documents` quattro volte; non Ã¨ un numero scelto a occhio.

- **Scelto: `MAX_STEPS=12`.** Ãˆ il massimo osservato (10) piÃ¹ due passi di margine.
- **Scartato: 8 e 20.** Con 8, `q06` si fermerebbe prima della risposta finale; con 20, un modello
  che continua a chiedere tool avrebbe venti chiamate prima del muro.
- **Lo so da:** la misura live di `q06` (10 passi) e
  `tests/test_g7.py::test_la_traccia_ricostruisce_il_run_e_la_pratica` (7 passi, 6 tool call).

### Estensione scelta: il budget si stima prima della chiamata
- **Scelto:** prima di ogni giro il loop stima input (messaggi piÃ¹ schemi dei tool, con margine di
  128 token) e output al tetto di 500 token; se `cost_eur + previsto > budget_eur`, si ferma con
  `stopped_by="budget"` senza chiamare il modello.
- **Scartato:** controllare solo dopo la chiamata, che pagherebbe comunque il giro che sfonda il
  tetto.
- **Lo so da:** `test_il_budget_si_ferma_prima_della_chiamata` prova tre soglie (`0.001`, `0.01`,
  `0.05`) con un messaggio enorme: zero chiamate, `steps=0`, costo zero. Resta dichiarato
  l'overshoot residuo: la stima non Ã¨ una misura, quindi una singola chiamata puÃ² ancora superare
  il tetto; il test esistente lo verifica con `run.cost_eur > BUDGET_PER_RUN`.

### Le prove di quello che non deve accadere
```bash
# 1. conto altrui in chiaro nella domanda: due rifiuti, nessun dato nel log
uv run pytest "tests/test_g7.py::test_il_muro_regge_con_l_iban_altrui_nella_domanda" -q
# 2. tetto dei passi: risposta assente, non una risposta inventata
uv run pytest "tests/test_g7.py::test_tetto_raggiunto_non_e_una_risposta" -q
# 3. budget: la chiamata non parte
uv run pytest "tests/test_g7.py::test_la_traccia_ricostruisce_il_run_e_la_pratica" -q
# 4. traccia: run e pratica ricostruibili, senza IBAN, importi o nomi
uv run pytest "tests/test_g7.py::test_la_traccia_ricostruisce_il_run_e_la_pratica" -q
# 5. idempotenza: due richieste uguali, una sola pratica
uv run pytest "tests/test_g7.py::test_due_segnalazioni_uguali_fanno_una_riga" -q
```

### Demo di due minuti
Con il server avviato e il corpus ingerito:
```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -d "username=mbianchi&password=bootcamp" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -s -X POST localhost:8000/api/ai/agent \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"Il cliente C-10234 ha ricevuto un bonifico di 25.000 EUR dal Venezuela: controlla i conti, il saldo e i movimenti, verifica la policy e, se serve, apri una segnalazione."}'
```
Nella prova del 2026-11-10 la risposta ha `steps=10`, `stopped_by=model`,
`cost_eur=0.003033` e la ricevuta della pratica
`e03952bf-f2b8-4f18-bdd8-efced8236d44` sul conto `IT60X0542811101000000123`, aperta da
`mbianchi` con importo `25000.00`. Rieseguendo la stessa domanda nello stesso giorno la pratica non
si duplica: la chiave di idempotenza comprende conto, autore, data e importo.

Poi il muro: la stessa richiesta sul conto di Anna Greco
(`IT60X0542811101000000789`) risponde 200 con `NON_DISPONIBILE`, `steps=2`,
`stopped_by=model`, costo `0.00032242`, `run_id=f0d2a3c7-d03d-44c4-9bb5-2aa3f7049f50`; nel log
compare `tool_accesso_negato` con l'impronta dell'IBAN, non l'IBAN. La traccia strutturata
(`agent_step` e `agent_run`) Ã¨ verificata nei test con `caplog`: il server non ha un formatter JSON,
quindi gli `extra` non compaiono nel formato standard del log. La risposta al client espone giÃ 
`run_id`, `steps`, `tool_calls`, `stopped_by` e `cost_eur`; il dettaglio completo del percorso Ã¨ in
`docs/vibe-coding/G7.md` e il rilievo di concorrenza non corretto Ã¨ in `docs/ai-review/G7.md`.

## Giorno 8 â€” approvazione, supervisor, server MCP

### Come si lancia
docker compose up -d && uv run alembic upgrade head && uv run python -m scripts.seed_accounts
uv run python -m scripts.seed_users
uv run uvicorn src.main:app --reload
uv run ruff check . && uv run mypy src tests liparibank_mcp scripts && uv run pytest
# server MCP, da provare da solo prima di collegarlo a un agente:
npx @modelcontextprotocol/inspector -e LIPARI_TOKEN=<token> uv run python -m liparibank_mcp.server

### Cosa fa
- POST /api/ai/agent: se un tool che scrive supera la soglia (SOGLIA_APPROVAZIONE_EUR, oggi 5000)
  o non ha importo, il run si ferma PRIMA che parta qualunque tool di quel passo, salva lo stato nel
  database (tabella agent_runs) e risponde stopped_by="awaiting_approval".
- GET /api/ai/agent/{id}, POST .../approve e .../reject: la decisione Ã¨ di compliance_lead o
  risk_lead, mai di chi ha chiesto. Alla ripresa i tool si rifanno per chi ha chiesto.
- POST /api/ai/supervisor: triage + al massimo due specialisti (dati_conto, policy) + sintesi.
  Nessuno specialista ha il tool che scrive: le azioni restano sull'endpoint dell'agente.
- liparibank_mcp/server.py: tre tool in sola lettura (search_policy, find_customer_accounts,
  get_account_balance), che riusano gli stessi tool dell'agente, quindi lo stesso muro del portafoglio.

### Decisioni, e come lo so
1. Lo stato del run sta nel database, non in memoria. Scartato: un dizionario nel processo, che un
   riavvio cancella. Lo so da un test che approva da un altro processo Python (test_g8), e da una
   prova a mano: non rieseguita in questa sessione; la persistenza è coperta dai test automatici esistenti (`tests/test_g8.py`).
2. La decisione si scrive con un UPDATE condizionato allo stato "in attesa", non con Â«leggi e poi
   scriviÂ». Scartato: il controllo in Python, che con due clic insieme li lascia passare entrambi.
   Lo so da un test con due richieste in parallelo: una 200 e una 409, una sola segnalazione.
3. La regola Ã¨ chiusa per default: un tool che scrive e non dichiara quando non serve l'approvazione
   la richiede sempre. Scartato: l'elenco dei tool "da proteggere", che dimentica il tool nuovo.
   Lo so da test_g7: un vecchio test con importo sopra soglia ha smesso di partire.
4. La soglia sta in configurazione e nel codice, non nel prompt. Lo so dall'esperimento 4 della
   Prompting Clinic: esperimento non rieseguito in questa sessione; la soglia resta applicata nel codice/configurazione (`settings.soglia_approvazione_eur`, tool/loop).
5. Il server MCP non riceve l'identitÃ  come parametro: la riceve come token firmato nell'ambiente e
   la verifica a ogni chiamata. Lo so da tre test: token vuoto, non valido e firmato con un altro
   segreto sono respinti.

### Costo e tempi
Stessa domanda su /agent e /supervisor: confronto non misurato live in questa sessione (richiede modello/API e corpus). Per misurarlo: inviare lo stesso payload ai due endpoint e confrontare `steps`/`tool_calls`/`cost_eur` (agent) vs numero chiamate/token/costo aggregato (supervisor).
Con un modello gratuito il costo Ã¨ 0: confronto fatto sul numero di chiamate e di token.

### Limiti noti
- Un run in attesa non scade e nessuno viene avvisato: resta lÃ¬ finchÃ© qualcuno non lo trova.
- Il token per il server MCP sta nell'ambiente del processo e vale 30 minuti: poi il server
  risponde Â«IdentitÃ  non verificataÂ» finchÃ© non si rilancia con un token nuovo.
- Con un modello che ragiona prima di rispondere, il triage (max_tokens=5) puÃ² non dare nessuna
  parola: il codice prende allora la strada prudente, "entrambi", che costa due specialisti.
- Le decisioni stanno in una colonna JSON: si leggono dall'endpoint di stato, non si interrogano
  con una query.

## Giorno 9 — qualità, eval e osservabilità

### Come si lancia
docker compose up -d
uv run alembic upgrade head
uv run python -m scripts.seed_accounts
uv run python -m evals.ingest_fixtures   # richiede OPENAI_API_KEY e embedding disponibili
uv run python -m evals.runner            # richiede OPENAI_API_KEY e Postgres; salva evals/results/latest.json
uv run pytest --cov=src

### Cosa è stato aggiunto
- `evals/`: golden dataset (`categorize` 40, `advice` 30, `agent_traiettorie` 15), judge rubric, ingest fixture, runner con salvataggio risultati e confronto `delta_vs_previous`.
- Osservabilità/costi: `src/observability/ledger.py` (`CostLedger` su `llm_calls`), `src/observability/json_log.py`, middleware `X-Request-Id`/log JSON in `src/main.py`, endpoint `GET /api/admin/cost-report`.
- CI eval: `.github/workflows/eval.yml` (`workflow_dispatch` + lunedì 06:00 UTC) con pgvector, migrate/seed/ingest/runner.
- Test G9: `tests/test_g9.py`; review: `docs/ai-review/G9.md`.

### Estensione scelta (runner)
- Scelta: confronto automatico con il run precedente (`evals/results/latest.json`, campo `delta_vs_previous`).
- Perché: evidenzia regressioni/miglioramenti tra valutazioni successive con un numero leggibile per suite.
- Prova: `tests/test_g9.py::test_runner_salva_risultato_e_delta`.

### Soglie e limiti
- Soglie iniziali runner: `categorize=0.80`, `advice=0.70`, `traiettorie=0.80` (da tarare con due run live consecutivi sotto rumore osservato; non misurato qui senza esecuzione live).
- `evals.runner`/`evals.ingest_fixtures` richiedono `OPENAI_API_KEY`, modello/embedding raggiungibili e DB con corpus/seed coerente.
