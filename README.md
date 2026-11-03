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
uv run mypy src
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