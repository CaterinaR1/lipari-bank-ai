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

Avvia il server con il comando Uvicorn coerente con il modulo main.py del progetto. Ad esempio, se il modulo è src/main.py:

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

Tempo misurato: da compilare dopo la prova.
Primo punto di blocco: da compilare dopo la prova.
Scelte delle dipendenze di sviluppo

Ruff, mypy e pytest sono strumenti di sviluppo e sono dichiarati nel gruppo dedicato di pyproject.toml. Sono separati dalle dipendenze runtime per evitare di installare strumenti di verifica nell'ambiente di produzione. La scelta viene verificata con uv sync --locked e con i tre comandi di controllo documentati sopra.

## Giorno 2 — come si lancia
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
  404, 405, 422 e 500. Il 500 non contiene traceback né percorsi di file.
- X-Request-Id: se il chiamante ne manda uno valido (8-64 caratteri fra lettere, cifre e
  trattini) torna uguale, altrimenti se ne genera uno.

## Importazione: righe buone importate, righe sbagliate spiegate
Ho tenuto la scelta del servizio: le righe valide si importano e ogni riga scartata si dichiara
col suo numero di riga.
Chi usa l'endpoint è un ufficio che carica un file al giorno: con 7 righe sbagliate su 200,
rifiutare tutto significherebbe perdere la giornata per un errore di 7 righe, mentre così sa
quali righe correggere. Ho scartato il rifiuto dell'intero file perché in quel caso l'ufficio non
saprebbe quali righe sono buone.
Lo so da un test: 16 righe di cui 10 sbagliate in modi diversi, e le righe dopo l'errore non
spariscono dal conto. Il conto torna sempre: righe non vuote = imported_count + len(problems).
Il costo: se l'ufficio carica di nuovo lo stesso file dopo averlo corretto, le righe già
importate si importano due volte. Oggi non importa, perché non c'è un database; dal Giorno 3 sì.

## Estensione scelta
(da compilare: tre righe, la proprietà dichiarata, il test che la dimostra)

## Giorno 3 — come si lancia
docker compose up -d
uv run alembic upgrade head
uv run python -m scripts.seed_accounts
uv run uvicorn src.main:app --reload
# test (database lipari_ai_test: docker compose exec postgres createdb -U lipari lipari_ai_test)
uv run ruff check . && uv run mypy src scripts && uv run pytest

## Chi chiude la transazione
Il commit sta nel service, una volta per operazione. Ho scartato il commit in `get_db`, perché
dopo lo yield gira quando la risposta è già partita: un commit che fallisce lascerebbe al client
un 200 per un dato che non c'è. Lo so da un test che fa fallire il commit e verifica il 500.

## Estensione: un movimento aggiorna anche il saldo
POST /api/ai/accounts/{id}/movements scrive il movimento e somma l'importo al saldo in una sola
transazione. Ho scartato di leggere il saldo e riscriverlo da Python (due richieste insieme si
sovrascrivono): la somma la fa Postgres con UPDATE ... SET balance = balance + :delta.
Lo so da un test che fa fallire l'aggiornamento del saldo e verifica che il movimento non resti.

## Importi con tre decimali
Si rifiutano con un 422. Ho scartato l'arrotondamento in silenzio di Numeric(12, 2): 12.345
diventerebbe 12.35 senza che nessuno lo sappia.

## Giorno 4 — come si lancia
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
`DEFAULT_MODEL` decide il fornitore nella factory (`src/llm/factory.py`): prefisso `claude` →
Anthropic, tutto il resto → OpenAI (o un endpoint compatibile indicato da `OPENAI_BASE_URL`).
Service, endpoint e tipi non cambiano.

OpenAI ↔ Anthropic: cambia solo `DEFAULT_MODEL`, perché entrambe le chiavi stanno nel `.env`.
Groq ↔ OpenRouter: sono due endpoint dello stesso SDK OpenAI, quindi cambiano `DEFAULT_MODEL`,
`OPENAI_BASE_URL` e `OPENAI_API_KEY`; il codice resta lo stesso. La prova del contratto fra due
implementazioni diverse del `Protocol` è nei test; la demo live gratuita usa Groq ↔ OpenRouter
perché Anthropic richiede una chiave a pagamento.

## L'output strutturato resta sull'SDK di OpenAI
La categorizzazione usa `instructor.from_openai(...)` (`src/llm/factory.py`): anche quando la chat
parla con Anthropic, l'output strutturato passa dall'SDK di OpenAI. Non ci sono due strade da
mantenere per lo stesso schema.

## Dove si conta il costo
Lo calcola il provider, che è l'unico a vedere i token consumati; il service somma i giri della
tool-call e salva una riga per risposta; il `CostTracker` legge la somma del giorno e la confronta
col tetto. Tengo questa divisione perché ogni pezzo fa una cosa sola e il tetto non deve fidarsi
del chiamante.

Il prezzo è quello di listino, non il tier gratuito: Groq `gpt-oss-120b` costa 0,00014/0,00056 EUR
per 1000 token e OpenRouter `:free` costa 0. Così il tetto conta quello che il fornitore
chiederebbe davvero e la demo mostra due costi diversi; con entrambi a zero il tetto non
scatterebbe mai.

## Estensione scelta: lo streaming sopravvive all'interruzione
Se il client chiude a metà, salvo il testo parziale già inviato e il suo costo stimato (~4
caratteri per token, dichiarato come stima) così il tetto non si aggira chiudendo la pagina. Ho
scartato di non salvare nulla perché avrebbe permesso di spendere senza contare. Lo so da un test:
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
# terminale 1 — Groq, costo a listino
$env:DEFAULT_MODEL="openai/gpt-oss-120b"; uv run uvicorn src.main:app --port 8000

# terminale 2 — OpenRouter, modello :free (chiave sk-or-v1-...)
$env:OPENAI_BASE_URL="https://openrouter.ai/api/v1"
$env:OPENAI_API_KEY="sk-or-v1-..."
$env:DEFAULT_MODEL="dots-studio/dots-3-note-preview:free"
uv run uvicorn src.main:app --port 8001
```
Poi, a parità di domanda:
```bash
curl -s -X POST localhost:8000/api/ai/chat -H "Content-Type: application/json" \
  -d '{"session_id":"new","message":"Quanto c e sul conto IT60X0542811101000000123?"}'
curl -s -X POST localhost:8001/api/ai/chat -H "Content-Type: application/json" \
  -d '{"session_id":"new","message":"Quanto c e sul conto IT60X0542811101000000123?"}'
```
I due `cost_eur` sono diversi perché i listini sono diversi; la forma della risposta e il percorso
sono gli stessi. Poi il tentativo sul conto di Anna Greco (`IT60X0542811101000000789`): risponde
lo strumento con un errore, e nel log compare `strumento_negato`. Per il 429 basta avviare con
`$env:DAILY_BUDGET_EUR="0"` e rifare una domanda.

La prova una-variabile OpenAI ↔ Anthropic resta la stessa: nel secondo terminale basta
`$env:DEFAULT_MODEL="claude-haiku-4-5-20251001"` e `ANTHROPIC_API_KEY` nel `.env`. Non l'ho
eseguita live perché la chiave Anthropic richiede un acquisto; la copre il test con le HTTP finte.

Il tier free di OpenRouter è limitato a 20 richieste al minuto e 50 al giorno senza crediti: basta
per questa demo, non per un uso reale. Alcuni modelli `:free` hanno anche un limite upstream: se
rispondono 429, cambia modello (per esempio `dots-studio/dots-3-note-preview:free` oppure
`openrouter/free`). I modelli `:free` possono usare i prompt per il training: usa solo i dati finti
del seed, mai dati reali di clienti.

## Giorno 5 — come si lancia
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
`POST /api/ai/documents/ingest`: il server deve essere già su. Il livello di visibilità è preso
dalla sottocartella (`public`, `internal`, `risk_only`, `compliance_only`). Gli embedding sono
locali (`EMBEDDING_BACKEND=local`, `intfloat/multilingual-e5-small`, 384 dimensioni): al primo uso
fastembed scarica il modello ONNX, poi resta nella cache. Non serve `EMBEDDING_API_KEY`; il
percorso OpenAI resta disponibile con `EMBEDDING_BACKEND=openai` e una chiave vera. Per i test
serve il database di prova:
`docker compose exec postgres createdb -U lipari lipari_ai_test`.

Le domande si fanno così, una volta che il corpus è nell'indice e l'utente ha fatto login:
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
  non sono addestrati a stare vicini. Ho scelto un modello locale perché non costa a chiamata,
  lascia i documenti dentro la macchina ed è deterministico nei test; pago il download del modello
  ONNX, l'uso di CPU e un tetto di qualità più basso di un modello API grande.
- **Chunk da 500 caratteri, sovrapposizione 50**: 500 tengono un concetto intero senza portarsi
  dietro mezzo documento; 50 evitano di perdere una frase che cade sul confine. Il taglio cerca
  prima `. `, `? `, `! ` e `\n\n` dopo metà finestra, e solo se non li trova taglia a 500. Prima
  del taglio tolgo i paragrafi identici (una pagina incollata due volte), perché con l'overlap le
  copie non sarebbero mai chunk uguali. Chunk più piccoli sono più precisi ma perdono contesto e
  fanno più chiamate; chunk più grandi mescolano più argomenti e il top-k porta rumore.
- **HNSW con coseno**: indice `vector_cosine_ops`, top-k 5, soglia di default 0.35 sul vettoriale.
  HNSW guadagna velocità (non confronta la domanda con tutti i vettori) e paga RAM, spazio, tempo
  di costruzione e insert più lenti. Senza indice la ricerca è esatta ma O(n). La variante ibrida
  alza il cancello a 0.85: su questi documenti i positivi in linguaggio naturale stanno da 0.852 in
  su, le negative plausibili fino a 0.851. Su un corpus nuovo va rimisurata; non è un numero
  universale.
- **Contesto etichettato**: ogni passaggio arriva al modello come
  `[fonte-N] (documento: ...)`, così può citare quello preciso e non un altro.
- **Citazioni**: `citazioni()` legge i `[fonte-N]` presenti nella risposta, accetta anche le
  parentesi larghe `【fonte-N】` che il modello produce a volte, scarta i numeri fuori intervallo e
  deduplica. Il client riceve i chunk davvero citati, non tutto il top-k.
- **Fuori soglia**: nessun passaggio vuol dire rifiuto, senza chiamare il modello; così non si
  spende per una domanda che i documenti non coprono.
- **Tetto e guasti**: l'advisor controlla lo stesso `CostTracker` della chat prima di spendere
  (429), salva la propria spesa in `cost_events` e un guasto dell'embedder o del modello diventa
  `LLMProviderError` (502), come nella chat.

## Estensione del Giorno 5: ricerca ibrida con cancello di plausibilità
L'ibrida resta disponibile con `RETRIEVAL_MODE=hybrid`; dal Giorno 6 il default è `vector` a 0.35,
perché la novità è il filtro per ruolo e non voglio sommare due variabili nella stessa misura.
Il vettore da solo trova quasi sempre il documento giusto, ma non sempre il passaggio giusto: su
importi e codici il coseno può mettere davanti un documento simile e lasciare fuori il chunk che
contiene il dato. Ho aggiunto una gamba lessicale `tsvector('italian')` con indice GIN e fuso i
ranghi con Reciprocal Rank Fusion (`1/(60 + posizione)`), non i punteggi: coseno e `ts_rank` hanno
scale diverse e sommarli farebbe vincere la lista con i numeri più alti per caso.

La ricerca lessicale gira in due versioni: **larga** (termini in OR) per la copertura, **stretta**
(termini in AND) per la precisione su "10.000 EUR" o su un codice composto. Il largo non può però
tirare dentro un documento che né il vettore (sopra 0.85) né lo stretto hanno trovato: se nessuno
dei due lo vede, la fusione torna vuota e la risposta è il rifiuto. È il **cancello di
plausibilità**, ed è quello che trasforma una domanda fuori corpus in zero passaggi invece di
cinque passaggi agganciati alla parola "conto".

Ho scartato:
- **sommare i punteggi grezzi** (coseno + `ts_rank`): numeri non confrontabili;
- **solo lessico**: trova i codici ma riempie il top-k di passaggi che condividono una parola;
- **alzare solo la soglia**: a 0.852 separerebbe l'ultima negativa, ma è a un millesimo dal
  positivo più debole; sarebbe overfitting su 16 domande. La soglia resta 0.85 e l'ultima negativa
  la gestisce il modello con il rifiuto.

La misura, con `k=5`, baseline vettoriale a soglia 0.35 e ibrida a 0.85:

| insieme | sistema | doc@5 | chunk@5 | doc@1 | MRR | negative con passaggi |
|----------|---------|-------|---------|-------|-----|------------------------|
| naturale (11+5) | vettoriale 0.35 | 11/11 | 11/11 | 10/11 | 0.955 | 5/5 |
| naturale (11+5) | vettoriale 0.85 | 11/11 | 10/11 | 10/11 | 0.955 | 1/5 |
| naturale (11+5) | ibrida 0.85 | 11/11 | 11/11 | 10/11 | 0.955 | 1/5 |
| esatte (20) | vettoriale 0.35 | 18/20 | 16/20 | 9/20 | 0.642 | — |
| esatte (20) | vettoriale 0.85 | 4/20 | 4/20 | 4/20 | 0.200 | — |
| esatte (20) | ibrida 0.85 | 18/20 | 18/20 | 17/20 | 0.875 | — |
| totale (31+5) | vettoriale 0.35 | 29/31 | 27/31 | 19/31 | 0.753 | 5/5 |
| totale (31+5) | ibrida 0.85 | 29/31 | 29/31 | 27/31 | 0.903 | 1/5 |

Il doc@5 non si muove fra baseline 0.35 e ibrida 0.85: sull'insieme naturale è già al tetto, e
sulle esatte i due sistemi sbagliano due domande diverse. Ma la tabella mostra perché servono
entrambe le cose: a 0.85 il vettoriale da solo perde 16 domande esatte su 20, perché il coseno di
un codice o di un importo spesso sta sotto soglia; a 0.35 le negative entrano tutte. L'ibrida
prende il meglio: il cancello a 0.85 tiene fuori 4 negative su 5, il lessico recupera i codici e
gli importi. Si muovono il passaggio giusto (chunk@5 0.871 → 0.935), il primo documento (doc@1
0.613 → 0.871), l'MRR (0.753 → 0.903) e le negative (5/5 → 1/5). I numeri si rifanno con:
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
1. domanda fuori corpus: rifiuto esatto, nessuna citazione, `tokens_used=0` e costo 0, cioè il
   modello non viene chiamato;
2. stesso documento caricato due volte: 2 → 2 passaggi, una citazione, una sola distinta;
3. pagina incollata due volte: 1 → 1 passaggio, una citazione, nessun doppione;
4. domanda vaga ("bonifico estero"): vettoriale e ibrida restituiscono passaggi e la risposta cita
   almeno una fonte; poi stampa i cinque passaggi, così si vede che cosa ha pescato.

## Su quali domande funziona e su quali no
Funziona sulle domande fattuali coperte da un passaggio dei documenti: "quanto costa il bonifico
istantaneo", "qual è il canone della carta oro", "quanto costano i prelievi ATM di altre banche".
Funziona anche sui codici e sugli importi esatti, dove il vettore da solo perde il passaggio:
`15.000 EUR`, `PRCEST07`, `€1.00`. Non funziona:
- fuori corpus (mutui, investimenti, prodotti che non ho caricato): risponde il rifiuto, che è il
  comportamento voluto;
- su due domande esatte con troppe parole ("A cosa serve la MODEST50?", "Dove trovo la Lista
  GRUPPO-A?"): il coseno scende sotto 0.85 e il lessico stretto non trova tutti i termini, quindi
  il cancello le scarta. Il lessico largo le troverebbe, ma è proprio quello che il cancello
  blocca per non far entrare le negative;
- su una negativa su cinque (`q16`, "documenti per aprire un conto titoli") il vettore resta a
  0.851 e passa la soglia: i passaggi arrivano, ma il modello risponde con il rifiuto (verificato
  live: 585 token, zero citazioni). È il rilievo che non ho corretto: alzare la soglia a 0.852 lo
  eliminerebbe sbilanciando il positivo più debole, e non è una scelta robusta su 16 domande;
- sulle domande che vogliono il dato di un cliente (saldo, movimenti): quello è il percorso
  chat/tool, non l'advisor, che non legge i conti;
- sulle domande che sommano più documenti senza un passaggio che li copra: il top-k porta i due
  pezzi ma la risposta può citarne uno solo;
- sui riferimenti impliciti ("e per la oro?"): fino al Giorno 5 il vettore della domanda da sola
  non conteneva il turno precedente. Dal Giorno 6 `AdviceRequest.history` porta gli ultimi turni al
  riscrittore; senza `history` il limite resta.

## Giorno 6 — chi sei e cosa puoi vedere
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
Marco (`operator`) non riceve la frase né una citazione `aml_controparti_venezuela`; Giulia
(`compliance_lead`) la riceve e cita il documento. Entrambe le risposte mostrano `rewritten_query`,
cioè cosa è stato cercato al posto dell'utente.

### Misura della riscrittura
`scripts/valuta_rewrite.py` usa un indice vero e le riscritture registrate nei due dataset, così il
numero si rifà senza chiave API (`--rigenera` le produce col modello, se serve). Con `k=5` e
soglia 0.35:

| misura | senza | con | delta |
|---|---|---|---|
| 10 domande, riscrittore | doc@1 0.900, MRR 0.950, doc@5 1.000 | doc@1 1.000, MRR 1.000, doc@5 1.000 | doc@1 +0.100, MRR +0.050 |
| 5 follow-up, storia | chunk@5 0.800, doc@1 0.200, MRR 0.500 | chunk@5 1.000, doc@1 0.800, MRR 0.900 | chunk@5 +0.200, doc@1 +0.600, MRR +0.400 |

La riga delle 10 domande è la linea di partenza richiesta dalla prima mezz'ora; la riga dei 5
follow-up è l'estensione. I follow-up grezzi (senza riscrittura) stanno a doc@5 0.400, quindi la
storia non è un dettaglio: senza, la domanda ellittica non contiene il documento giusto.

### Estensione scelta: la storia nel riscrittore
- **Scelto**: `AdviceRequest.history` porta gli ultimi turni; `rewrite_cached` mette nella chiave
  gli ultimi tre, così la riscrittura di una conversazione non si riusa in un'altra.
- **Scartato**: la cache solo-domanda (restituisce la riscrittura di un'altra conversazione) e la
  riscrittura senza storia (non risolve "e per quello di prima?").
- **Numero**: sui 5 follow-up il MRR passa da 0.500 a 0.900, il chunk@5 da 0.800 a 1.000 e il
  doc@1 da 0.200 a 0.800. Il prezzo è che la cache si riusa solo dentro la stessa conversazione.

## Demo di due minuti
1. `docker compose up -d && uv run alembic upgrade head && uv run python -m scripts.seed_users`.
2. `uv run uvicorn src.main:app --reload` in un secondo terminale, poi
   `uv run python -m scripts.ingest_docs`.
3. Login di Marco e Giulia con le due funzioni `login` qui sopra; stessa domanda canarino a
   entrambi: Marco non vede la frase, Giulia sì, con le due liste di fonti accanto e
   `rewritten_query` visibile in entrambe.
4. Domanda con la storia:
   `-d '{"question":"E per i clienti storici?","history":["Qual è il canone annuo della carta oro?"]}'`
   e mostrare `rewritten_query` = "Qual è il canone annuo della carta di credito oro per i clienti
   storici?".
5. `uv run python -m scripts.valuta_rewrite && uv run python -m scripts.valuta_rewrite --storia`:
   le due tabelle con i delta.