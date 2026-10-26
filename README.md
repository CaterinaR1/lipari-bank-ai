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