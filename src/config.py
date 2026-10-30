# src/config.py
import re
import sys
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError


class Settings(BaseSettings):
    """La configurazione del progetto, letta dall'ambiente e dal file .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LipariBank AI"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False

    database_url: str = Field(
        min_length=1,
        description=(
            "la stringa di connessione, postgresql+asyncpg://utente:password@host:5432/nome"
        ),
    )
    jwt_secret: str = Field(
        min_length=32,
        description=(
            "un segreto di almeno 32 caratteri: "
            'uv run python -c "import secrets; '
            'print(secrets.token_urlsafe(48))"'
        ),
    )

    openai_api_key: str = ""
    anthropic_api_key: str = ""

    default_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    max_tokens_per_request: int = 2000

    cors_origins: list[str] = ["http://localhost:5173"]


def spiega(errore: ValidationError) -> str:
    """Traduce gli errori di configurazione in messaggi leggibili."""

    righe = ["Configurazione non valida: il progetto non parte."]

    for e in errore.errors():
        campo = str(e["loc"][0])
        info = Settings.model_fields.get(campo)

        stato = "manca" if e["type"] == "missing" else f"valore non valido ({e['msg']})"

        cosa = f" Ci va {info.description}." if info and info.description else ""
        righe.append(f"  - {campo.upper()}: {stato}.{cosa}")

    righe.append("Si scrive nel file .env (l'elenco completo sta in .env.example) o nell'ambiente.")

    return "\n".join(righe)


def carica() -> Settings:
    """Carica e valida la configurazione all'avvio."""

    try:
        return Settings()
    except ValidationError as e:
        sys.exit(spiega(e))
    except SettingsError as e:
        # dal Giorno 2: un valore che non si riesce nemmeno a leggere, come una lista senza JSON
        trovato = re.search(r'field "(\w+)"', str(e))
        nome = trovato.group(1).upper() if trovato else "una variabile"
        sys.exit(
            "Configurazione non valida: il progetto non parte.\n"
            f"  - {nome}: valore non leggibile. Una lista si scrive in JSON, per esempio "
            '["http://localhost:5173"].'
        )


settings = carica()
